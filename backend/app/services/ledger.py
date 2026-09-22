"""账本核心操作 —— 记一笔、归期、算余额。

这里是唯一允许写 entry_share 的地方。别处要算钱，一律读快照。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Sequence

from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.core.rules import expand, mkey, participants, pick_rule
from app.core.split import split
from app.models import (
    AuditLog,
    Bundle,
    Category,
    Entry,
    EntryKind,
    EntryShare,
    Member,
    now_utc,
    today_jst,
)
from app.services import settings as settings_svc


#: PATCH 一笔账时不许被清空的字段。数据库上就是 NOT NULL，
#: 传 null 进来原来会撞成 500
_NOT_NULLABLE = ("kind", "date", "amount_jpy", "payer_id", "title", "note")


class LedgerError(ValueError):
    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------ 成员


def active_members(session: Session, on: dt.date | None = None) -> list[Member]:
    """某天在籍的成员，按 display_order 排。这个顺序也是分摊平局时的排序依据。"""
    on = on or today_jst()
    rows = session.exec(select(Member).order_by(Member.display_order, Member.id)).all()
    return [m for m in rows if m.is_active(on)]


# ------------------------------------------------------------------ 记一笔


#: 金额上界。超过这个数就不是手滑，是输错了。
#: 不设上界的话 10**19 会一路撞到 SQLite 的 INTEGER 上溢出成 500；
#: 而 10**18 更坏 —— 它**存得进去**，从此每张账单的合计都带着它，
#: 全局余额恒等式照样成立，屏幕上却没有一处能看出哪笔账错了。
MAX_AMOUNT = 1_000_000_000_000


#: 文本字段的上限。不设的话 10 万字的备注也照收 —— 界面被撑爆，库也白胖。
#: 前端的备注框本来就是 maxlength=40，这里给的是接口层的兜底
MAX_TITLE = 200
MAX_NOTE = 2_000
#: 业务日期的上下界。9999-12-31 原来是收的，而它会把草稿账单的覆盖期顶到 9999 年
MIN_DATE = dt.date(2000, 1, 1)
MAX_DATE_AHEAD = 366        # 最多提前一年（预付一整年的房租是真会有的事）


def _validate_amount(kind: EntryKind, amount: int) -> None:
    # bool 这一支只挡得住**服务层**的调用（测试、种子、carry）：走 HTTP 进来的话
    # Pydantic 早就把 true 转成 1 了，轮不到这里说话
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise LedgerError("not_integer", f"金额必须是整数日元，收到 {amount!r}")
    if abs(amount) > MAX_AMOUNT:
        raise LedgerError(
            "amount_too_large",
            f"金额超过上限 {MAX_AMOUNT}：{amount}",
            limit=MAX_AMOUNT,
        )
    if amount == 0:
        raise LedgerError("zero_amount", "金额不能是 0")
    if kind == EntryKind.expense and amount < 0:
        raise LedgerError("bad_sign", "支出金额要填正数；退款/返现请记成「收入」")
    if kind == EntryKind.income and amount > 0:
        raise LedgerError("bad_sign", "收入金额存为负数（返现是大家一起收的钱）")
    if kind == EntryKind.settlement and amount < 0:
        raise LedgerError("bad_sign", "转账金额要填正数；方向反了就把转出/转入对调")


def _validate_text(title: str, note: str) -> None:
    if len(title) > MAX_TITLE:
        raise LedgerError("text_too_long", f"备注最多 {MAX_TITLE} 字", field="title", limit=MAX_TITLE)
    if len(note) > MAX_NOTE:
        raise LedgerError("text_too_long", f"说明最多 {MAX_NOTE} 字", field="note", limit=MAX_NOTE)


def _validate_date(on: dt.date) -> None:
    if not isinstance(on, dt.date):
        raise LedgerError("bad_date", f"日期不对：{on!r}")
    if on < MIN_DATE or on > today_jst() + dt.timedelta(days=MAX_DATE_AHEAD):
        raise LedgerError("bad_date", f"日期超出范围：{on}", min=MIN_DATE.isoformat())


def _check_refs(
    session: Session,
    *,
    payer_id: int | None = None,
    to_member_id: int | None = None,
    member_ids: Sequence[int] | None = None,
    category_id: int | None = None,
    bundle_id: int | None = None,
) -> None:
    """引用到的成员/分类/套餐必须真实存在。

    不查的话，不存在的 id 会一路撞到数据库的外键约束上，返回 500 ——
    客户端拿到的是一句「服务器错误」，既看不出是哪个字段，也不知道能不能重试。
    """
    for label, mid in (("付款人", payer_id), ("转入人", to_member_id)):
        if mid is not None and session.get(Member, mid) is None:
            raise LedgerError("unknown_member", f"{label}不存在：{mid}", member_id=mid)
    for mid in member_ids or ():
        if session.get(Member, mid) is None:
            raise LedgerError("unknown_member", f"参与人不存在：{mid}", member_id=mid)
    if category_id is not None and session.get(Category, category_id) is None:
        raise LedgerError("unknown_category", f"分类不存在：{category_id}", category_id=category_id)
    # bundle 是这里唯一漏掉过的外键：乱指一个 id 会一路撞到数据库的约束上返回 500，
    # 而这个函数存在的全部理由就是别让那种事发生
    if bundle_id is not None and session.get(Bundle, bundle_id) is None:
        raise LedgerError("unknown_bundle", f"套餐不存在：{bundle_id}", bundle_id=bundle_id)


def create_entry(
    session: Session,
    *,
    actor_id: int | None,
    kind: EntryKind,
    on: dt.date,
    amount: int,
    payer_id: int,
    rule: dict[str, Any] | None = None,
    category_rule: dict[str, Any] | None = None,
    member_ids: Sequence[int] | None = None,
    to_member_id: int | None = None,
    category_id: int | None = None,
    title: str = "",
    note: str = "",
    bundle_id: int | None = None,
) -> Entry:
    """记一笔，并把分摊结果**固化**成 entry_share。

    分摊只在这一刻算一次。之后改默认比例、加成员、删分类，这条账都不会变。
    """
    _check_refs(session, payer_id=payer_id, to_member_id=to_member_id,
                member_ids=member_ids, category_id=category_id, bundle_id=bundle_id)
    _validate_amount(kind, amount)
    _validate_text(title, note)
    _validate_date(on)

    if kind == EntryKind.settlement:
        if to_member_id is None:
            raise LedgerError("missing_to_member", "转账必须指定转入人")
        if to_member_id == payer_id:
            raise LedgerError("self_transfer", "不能转给自己")
        # 转账＝付款人交钱、收款人的「应担」增加同样多。套进同一条余额公式里。
        expanded = {"mode": "exact", "exact": {mkey(to_member_id): amount}}
        ids: list[int] = [to_member_id]
    else:
        ids = list(member_ids) if member_ids is not None else [m.id for m in active_members(session, on)]
        if not ids:
            raise LedgerError("no_participants", "这一天没有在籍成员，没法分摊")
        global_rule = settings_svc.get(session, "default_rule")
        expanded = expand(pick_rule(rule, category_rule, global_rule), ids)

    remainder_to = settings_svc.get(session, "remainder_to")
    if kind != EntryKind.settlement and not expanded.get("remainder_to"):
        expanded["remainder_to"] = remainder_to

    entry = Entry(
        kind=kind,
        date=on,
        title=title,
        amount_jpy=amount,
        category_id=category_id,
        payer_id=payer_id,
        to_member_id=to_member_id,
        bundle_id=bundle_id,
        split_rule_json=expanded,
        note=note,
        created_by=actor_id,
    )
    session.add(entry)
    session.flush()

    _write_shares(session, entry, expanded, payer_id)
    _audit(session, actor_id, "create", "entry", entry.id, None, _snapshot(session, entry))
    session.commit()
    session.refresh(entry)
    return entry


def _canonical_order(session: Session, keys: Iterable[str]) -> list[str]:
    """把参与人按**成员表的固定顺序**排（display_order，再 id）。

    余数归谁是靠「成员在 order 里的下标」决胜的，所以这个顺序绝不能是
    「客户端送上来的那个字典碰巧是什么顺序」：
      * 客户端没送规则时，后端按 display_order 展开；而记一笔那屏的分摊预览
        用的是「自己排第一」的展示顺序 —— 同一笔账，预览和落库能差 1 円，
        而且换个人登录差的还是另一个人。
      * 客户端送了规则时，字典顺序就是那台手机上的展示顺序 —— 同一条规则由
        不同的人录入，分摊结果会不一样。
    排完之后，谁录的、谁在看，都不影响这笔钱怎么分。
    """
    rank = {
        mkey(m.id): (m.display_order, m.id)
        for m in session.exec(select(Member).order_by(Member.display_order, Member.id))
    }
    return sorted(keys, key=lambda k: rank.get(k) or (10**9, int(k)))


def _write_shares(session: Session, entry: Entry, expanded: dict[str, Any], payer_id: int) -> None:
    """算分摊 → 断言合计 → 落库。entry_share 只在这里被写。"""
    order = _canonical_order(session, participants(expanded))
    shares = split(
        expanded,
        entry.amount_jpy,
        order=order,
        payer=mkey(payer_id),
        rotate_seed=entry.id or 0,
    )
    total = sum(shares.values())
    if total != entry.amount_jpy:  # pragma: no cover —— 引擎已保证，这是最后一道闸
        raise LedgerError("sum_mismatch", f"分摊合计 {total} ≠ 总额 {entry.amount_jpy}")
    # **逐条也要有上界。** MAX_AMOUNT 只卡 entry.amount_jpy，而真正落库的钱是
    # entry_share：ratio 模式下 base = amount − Σadjustments，一个巨大的调整额
    # 能把每个人的 share 打成天文数字，而**合计仍严格等于 amount** ——
    # 于是「Σ余额≡0」「Σshares≡amount」两条自检全绿，屏幕上却看不出哪笔账错了。
    # entry_share 只在这里写，这一处同时管住 POST / PATCH / carry / 分类规则 / 全局规则
    for key, value in shares.items():
        if abs(value) > MAX_AMOUNT:
            raise LedgerError(
                "share_too_large", f"某个人的应担超出上限：{value}",
                member=key, limit=MAX_AMOUNT,
            )

    session.exec(  # type: ignore[call-overload]
        EntryShare.__table__.delete().where(EntryShare.entry_id == entry.id)
    )
    for key, value in shares.items():
        session.add(EntryShare(entry_id=entry.id, member_id=int(key), amount_jpy=value))
    session.flush()


# ------------------------------------------------------------------ 余额


def balances(session: Session) -> dict[int, int]:
    """balance = Σ我付出的 − Σ我应担的。

    正数＝别人欠我，负数＝我欠别人。全体之和恒等于 0 —— 这是最强的自检。
    软删的账不算。
    """
    paid: dict[int, int] = {
        row[0]: int(row[1] or 0)
        for row in session.exec(
            select(Entry.payer_id, func.sum(Entry.amount_jpy))
            .where(Entry.deleted_at.is_(None))
            .group_by(Entry.payer_id)
        )
    }
    owed: dict[int, int] = {
        row[0]: int(row[1] or 0)
        for row in session.exec(
            select(EntryShare.member_id, func.sum(EntryShare.amount_jpy))
            .join(Entry, Entry.id == EntryShare.entry_id)
            .where(Entry.deleted_at.is_(None))
            .group_by(EntryShare.member_id)
        )
    }
    member_ids = [m.id for m in session.exec(select(Member).order_by(Member.display_order, Member.id))]
    return {m: paid.get(m, 0) - owed.get(m, 0) for m in member_ids}


# ------------------------------------------------------------------ 留痕


def _snapshot(session: Session, entry: Entry) -> dict[str, Any]:
    shares = session.exec(select(EntryShare).where(EntryShare.entry_id == entry.id)).all()
    data = entry.model_dump(mode="json")
    data["shares"] = {str(s.member_id): s.amount_jpy for s in shares}
    return data


def _audit(
    session: Session,
    actor_id: int | None,
    action: str,
    table: str,
    target_id: int | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        AuditLog(
            at=now_utc(),
            member_id=actor_id,
            action=action,
            target_table=table,
            target_id=target_id,
            before_json=before,
            after_json=after,
        )
    )


# ------------------------------------------------------------------ 改 / 删


def update_entry(
    session: Session,
    entry: Entry,
    *,
    actor_id: int | None,
    version: int,
    fields: dict[str, Any],
    rule: dict[str, Any] | None = None,
    category_rule: dict[str, Any] | None = None,
    member_ids: Sequence[int] | None = None,
) -> Entry:
    """改一笔账。改完**当场重算这一笔**的分摊，其它账一概不动。

    version 是乐观锁：两个人同时改同一笔时，后提交的那个会被挡下来，
    而不是悄悄覆盖掉对方的修改。
    """
    # PATCH 里**显式传 null** 的字段：不能留空的那几个一律当成错误挡下来。
    # 原来是直接 setattr 下去，title=None 撞 NOT NULL、kind=None 撞 _validate_amount，
    # 两条都是 500 —— 而客户端拿到「服务器错误」既看不出哪个字段，也不知道能不能重试。
    # left_on / category_id / to_member_id / bundle_id 不在这张表里：它们**可以**被清空
    nulled = [k for k in _NOT_NULLABLE if k in fields and fields[k] is None]
    if nulled:
        raise LedgerError(
            "null_field", f"这些字段不能清空：{', '.join(nulled)}", fields=", ".join(nulled)
        )

    if entry.deleted_at is not None:
        # 回收站里的账不许改。原来改得动而且返回 200：那边界面上已经删掉了，
        # 这边却在给它重算分摊、写审计日志，谁也不知道这笔账到底是什么状态
        raise LedgerError("entry_deleted", "这笔账已经删掉了，先撤销删除再改")

    # 乐观锁必须是**一条语句**。原来是「先读出来比一比，再写回去」：
    # 两个人同时改同一笔，两边都读到 version=1、都觉得没冲突，然后各写各的；
    # 而写 entry 和写 entry_share 又是分开两步，交错之后能留下
    # 「金额是后写那个人的、分摊还是先写那个人的」这种 Σshares ≠ amount 的账 ——
    # 那是全局余额恒等式的地基。下面这条 UPDATE ... WHERE version = ? 由数据库
    # 保证只有一个人抢得到
    claimed = session.execute(
        sa_update(Entry).where(Entry.id == entry.id, Entry.version == version).values(version=version + 1)
    )
    if claimed.rowcount == 0:
        session.rollback()
        session.refresh(entry)
        raise LedgerError(
            "version_conflict",
            "这笔账刚被人改过，请刷新后重试",
            expected=entry.version,
            got=version,
        )
    entry.version = version + 1     # ORM 手里那份跟上，后面 add() 才不会写回旧值
    before = _snapshot(session, entry)
    prev_kind = entry.kind          # 下面几行就要被覆盖掉，先留一份
    prev_category_id = entry.category_id

    for key in ("title", "note", "category_id", "bundle_id"):
        if key in fields:
            setattr(entry, key, fields[key])

    amount = fields.get("amount_jpy", entry.amount_jpy)
    kind = fields.get("kind", entry.kind)
    on = fields.get("date", entry.date)
    payer_id = fields.get("payer_id", entry.payer_id)
    to_member_id = fields.get("to_member_id", entry.to_member_id)
    _check_refs(session, payer_id=payer_id, to_member_id=to_member_id,
                member_ids=member_ids, category_id=fields.get("category_id"),
                bundle_id=fields.get("bundle_id"))
    _validate_amount(kind, amount)
    _validate_text(fields.get("title", entry.title), fields.get("note", entry.note))
    _validate_date(on)

    entry.kind, entry.date, entry.amount_jpy = kind, on, amount
    entry.payer_id, entry.to_member_id = payer_id, to_member_id

    if kind == EntryKind.settlement:
        if to_member_id is None:
            raise LedgerError("missing_to_member", "转账必须指定转入人")
        if to_member_id == payer_id:
            raise LedgerError("self_transfer", "不能转给自己")
        expanded = {"mode": "exact", "exact": {mkey(to_member_id): amount}}
    else:
        # **从转账改成支出/收入时，旧规则一点都不能继承。**
        # 转账的规则是 {"mode":"exact","exact":{转入人: 全额}}，拿它当分摊基准
        # 会把整笔钱算到当初那个转入人头上 —— 悄无声息，谁也看不出来。
        inheritable = prev_kind != EntryKind.settlement

        if member_ids is not None:
            ids = list(member_ids)
        else:
            # 参与人按「谁最有发言权」取：
            #   1. 这次提交的规则自己点名的人 —— 用户刚在分摊面板上选好的。
            #      不认它的话，新室友搬进来之后改任何一笔旧账都会被 expand()
            #      以 unknown_member 挡死，那笔账从此再也改不动
            #   2. 这笔账原来的参与人（**不按新日期重挑**：改日期不该换人）
            #   3. 实在没有，才按这笔账的日期取在籍成员
            from_rule = [int(k) for k in participants(rule)] if rule is not None else []
            from_entry = [int(k) for k in participants(entry.split_rule_json)] if inheritable else []
            ids = from_rule or from_entry or [m.id for m in active_members(session, on)]
            # 参与人从规则里推出来时，得自己再验一遍存在性 —— 上面那次 _check_refs
            # 验的是 body 里显式传的 member_ids。规则里点名一个不存在的 id 的话，
            # expand() 会觉得「规则和参与人对得上」放行，一直到写 entry_share 才撞外键：
            # 同一个输入走 POST 是规规矩矩的 400，走 PATCH 却是 500
            _check_refs(session, member_ids=ids)

        # 换了分类就该用新分类的默认分摊 —— 界面上分摊预览当场就变成新分类的样子了，
        # 继续沿用旧规则的话，存下去和刚才看到的不是一回事
        category_changed = entry.category_id != prev_category_id
        global_rule = settings_svc.get(session, "default_rule")
        keep_old = member_ids is None and inheritable and not category_changed
        base = rule if rule is not None else (entry.split_rule_json if keep_old else None)
        expanded = expand(pick_rule(base, category_rule, global_rule), ids)
        if not expanded.get("remainder_to"):
            expanded["remainder_to"] = settings_svc.get(session, "remainder_to")

    entry.split_rule_json = expanded
    entry.updated_at = now_utc()   # version 在最上面那条 UPDATE 里已经加过了
    session.add(entry)
    session.flush()

    _write_shares(session, entry, expanded, payer_id)
    _audit(session, actor_id, "update", "entry", entry.id, before, _snapshot(session, entry))
    session.commit()
    session.refresh(entry)
    return entry


def delete_entry(session: Session, entry: Entry, *, actor_id: int | None) -> None:
    """软删，进回收站。分摊快照留着 —— 但余额不再算它。"""
    before = _snapshot(session, entry)
    entry.deleted_at = now_utc()
    # version 也要推进：别人手里那份就此过期。不推的话，另一台手机拿着删除前的
    # version 去改，乐观锁还以为没人动过
    entry.version += 1
    session.add(entry)
    _audit(session, actor_id, "delete", "entry", entry.id, before, None)
    session.commit()


def restore_entry(session: Session, entry: Entry, *, actor_id: int | None) -> None:
    """从回收站捞回来。"""
    entry.deleted_at = None
    entry.version += 1
    session.add(entry)
    _audit(session, actor_id, "restore", "entry", entry.id, None, _snapshot(session, entry))
    session.commit()
