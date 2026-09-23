"""账单 —— 按「点出账单的那一刻」切，不按日历切。

    还没出账的账目（statement_id IS NULL）合起来就是**当前这张草稿账单**。
    点「出账单」＝ 把它们一次性归到一张 Statement 上、冻结快照，
    之后再记的账自动进下一张。

这么做去掉了一整套按日历归期的机制：起算日、月份边界、「这笔落进了哪一期」、
改起算日导致账期重叠、关账/解锁。那些问题全是日历边界自己造出来的。

**不锁定历史**。余额是全局累计的，事后改一笔已出账的账，差额会原样出现在
下一张的「上期结转」里，钱不会算错。所以不需要「关账」这道门 ——
只需要把「这一期在出账后被改过」这件事**显示出来**，让结转解释得清。

账单展示 = 上期结转 + 本期发生 + 本期已收付：

    closing = opening + (已垫付 − 应担) + (转出 − 转入)
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from sqlalchemy import case, func, or_, union_all
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.core.settle import Transfer, plan_pairwise, plan_simplified
from app.models import (
    AuditLog,
    Category,
    Entry,
    EntryKind,
    EntryShare,
    Member,
    Statement,
    now_utc,
    jst_date,
    today_jst,
)
from app.services import ledger
from app.services import settings as settings_svc


# ------------------------------------------------------------------ 取数


def unbilled(session: Session) -> list[Entry]:
    """还没出账的账目 —— 它们合起来就是当前这张草稿账单。"""
    return list(
        session.exec(
            select(Entry)
            .where(Entry.statement_id.is_(None), Entry.deleted_at.is_(None))
            .order_by(Entry.date, Entry.id)
        )
    )


def entries_of(session: Session, statement_id: int) -> list[Entry]:
    return list(
        session.exec(
            select(Entry)
            .where(Entry.statement_id == statement_id, Entry.deleted_at.is_(None))
            .order_by(Entry.date, Entry.id)
        )
    )


def _shares_of(session: Session, entry_ids: list[int]) -> dict[int, dict[int, int]]:
    if not entry_ids:
        return {}
    # 只取三列，不把每一行分摊都造成 ORM 对象：一张账单几百笔 × 三个人，
    # 光是造对象就占了取数的一大半
    out: dict[int, dict[int, int]] = {}
    for eid, mid, amount in session.exec(
        select(EntryShare.entry_id, EntryShare.member_id, EntryShare.amount_jpy).where(
            EntryShare.entry_id.in_(entry_ids)
        )
    ):
        out.setdefault(eid, {})[mid] = amount
    return out


def _earlier_ids(session: Session, statement: Statement | None) -> list[int] | None:
    """这张账单**之前**出过的那些单子。None ＝ 不限（草稿：全部出过账的都算）。"""
    if statement is None:
        return None
    # 只要 id。整行取的话每张单子的快照 JSON 都要解析一遍，而这里一个字都用不上
    return list(session.exec(select(Statement.id).where(Statement.cut_at < statement.cut_at)))


def _scope_billed(stmt, ids: list[int] | None):
    """把查询限定在「这张账单之前出过账的那些账目」上。"""
    stmt = stmt.where(Entry.deleted_at.is_(None), Entry.statement_id.is_not(None))
    return stmt if ids is None else stmt.where(Entry.statement_id.in_(ids))


def _opening(session: Session, statement: Statement | None) -> dict[int, int]:
    """上期结转 ＝ 这张账单之前的全部账目让每个人净赚/净欠多少。

    **用 SQL 聚合，不把账本搬进内存。** 原来的写法是先把之前所有 Entry 全部 ORM 化，
    再把它们的 EntryShare 全部捞出来在 Python 里一条条加。
    账单页是这个 App 最常开的一屏，而这个成本**随历史线性增长，永远只会更慢** ——
    实测 5 年 3000 笔时 build_bill 要 120ms，其中 110ms 花在这里，
    而 ledger.balances() 干同样的活只要 3.4ms，差的就是这两条 group by。
    """
    ids = _earlier_ids(session, statement)
    if ids is not None and not ids:
        return {}
    # **垫付和应担必须在同一条 SQL 里数完。**
    # 分成两条 SELECT 的话它们不在同一个快照上 —— pysqlite 不会为 SELECT 开事务，
    # 每条自己取一次最新状态。于是别人在这两条之间记了一笔（手机上按下保存，
    # 电脑上正好在看账单），这边就会「数到了他垫的钱、没数到他应担的份」，
    # 算出一本不平的账 → settle.plan 抛 unbalanced → GET /api/bill 直接 500。
    # 账是好的，只是被看的那一瞬间是斜的。一条 UNION ALL + 一次 group by 就没这个缝
    deltas = union_all(
        _scope_billed(
            select(Entry.payer_id.label("mid"), Entry.amount_jpy.label("delta")), ids
        ),
        _scope_billed(
            select(
                EntryShare.member_id.label("mid"),
                (-EntryShare.amount_jpy).label("delta"),
            ).join(Entry, Entry.id == EntryShare.entry_id),
            ids,
        ),
    ).subquery()
    return {
        mid: int(total or 0)
        for mid, total in session.exec(
            select(deltas.c.mid, func.sum(deltas.c.delta)).group_by(deltas.c.mid)
        )
    }


def _opening_and_live(
    session: Session, statement: Statement, member_ids: list[int]
) -> tuple[dict[int, int], dict[int, int]]:
    """一张出过的账单要的两份余额，**一条 SQL 数完**：
    上期结转（这张之前出过账的那些）和此刻的实时余额（全部没删的账）。

    原来是 _opening 一遍、ledger.balances 又一遍，两次都把整本账扫一遍；
    而且两条 SELECT 不在同一个快照上（理由见 _opening 里那段）。
    """
    ids = _earlier_ids(session, statement)
    if not ids:
        # 头一张：没有上期结转。这时合并反而更慢（多一个用不上的条件列）
        live = ledger.balances(session)
        return {}, {m: live.get(m, 0) for m in member_ids}
    deltas = union_all(
        select(Entry.statement_id.label("st"), Entry.payer_id.label("mid"), Entry.amount_jpy.label("delta"))
        .where(Entry.deleted_at.is_(None)),
        select(
            Entry.statement_id.label("st"),
            EntryShare.member_id.label("mid"),
            (-EntryShare.amount_jpy).label("delta"),
        )
        .join(Entry, Entry.id == EntryShare.entry_id)
        .where(Entry.deleted_at.is_(None)),
    ).subquery()
    opening: dict[int, int] = {}
    live: dict[int, int] = {}
    for mid, before, now in session.exec(
        select(
            deltas.c.mid,
            # 草稿里的账 statement_id 是 NULL，NULL IN (...) 不成立 —— 正好不算进结转
            func.sum(case((deltas.c.st.in_(ids), deltas.c.delta), else_=0)),
            func.sum(deltas.c.delta),
        ).group_by(deltas.c.mid)
    ):
        if before:
            opening[mid] = int(before)
        live[mid] = int(now or 0)
    return opening, {m: live.get(m, 0) for m in member_ids}


def _covers_from(prev: Statement | None, dates: list[dt.date]) -> str | None:
    """这张单子的覆盖期从哪天算起。

    正常就是**上一次出账那天** —— 它管的是那之后的一切。头一张没有上一次，
    从第一笔算起。

    但补录/回收站恢复出来的账，日期可能比上次出账还早（记一笔的日期下限只挡新记的，
    改已有的那笔不受限）。真出现了就取更早的那个 —— 否则「7/28 〜 7/2」这种
    头尾颠倒的区间会直接摆在账单顶上。
    """
    if not dates:
        return None
    first = min(dates)
    if prev is None:
        return first.isoformat()
    return min(jst_date(prev.cut_at), first).isoformat()


# ------------------------------------------------------------------ 账单


def build_bill(session: Session, statement: Statement | None = None) -> dict[str, Any]:
    """statement 传 None ＝ 当前这张还没出的草稿账单。"""
    entries = unbilled(session) if statement is None else entries_of(session, statement.id)
    shares = _shares_of(session, [e.id for e in entries])
    members = list(session.exec(select(Member).order_by(Member.display_order, Member.id)))
    if statement is None:
        opening = _opening(session, None)
        live_balances: dict[int, int] | None = None
    else:
        opening, live_balances = _opening_and_live(session, statement, [m.id for m in members])

    owed: dict[int, int] = {}
    paid: dict[int, int] = {}
    out_: dict[int, int] = {}
    in_: dict[int, int] = {}
    total_expense = total_income = 0

    for e in entries:
        if e.kind == EntryKind.settlement:
            out_[e.payer_id] = out_.get(e.payer_id, 0) + e.amount_jpy
            if e.to_member_id is not None:
                in_[e.to_member_id] = in_.get(e.to_member_id, 0) + e.amount_jpy
            continue
        paid[e.payer_id] = paid.get(e.payer_id, 0) + e.amount_jpy
        for m, sh in shares.get(e.id, {}).items():
            owed[m] = owed.get(m, 0) + sh
        if e.kind == EntryKind.expense:
            total_expense += e.amount_jpy
        else:
            total_income += e.amount_jpy

    rows = []
    closing: dict[int, int] = {}
    for m in members:
        o = opening.get(m.id, 0)
        c = o + (paid.get(m.id, 0) - owed.get(m.id, 0)) + (out_.get(m.id, 0) - in_.get(m.id, 0))
        closing[m.id] = c
        # 搬走的人：**还有账就留着，全零就不占位**。
        # 欠着钱走的必须一直挂在账单上直到结清（这也是「退出不删人」的意义）；
        # 但结清了还天天占一行 0，往后每张账单都得带着前室友的名字
        moved_out_and_clear = not m.is_active() and not (
            o or c or owed.get(m.id) or paid.get(m.id) or out_.get(m.id) or in_.get(m.id)
        )
        if moved_out_and_clear:
            continue
        rows.append(
            {
                "member_id": m.id,
                "opening": o,
                "owed": owed.get(m.id, 0),
                "paid": paid.get(m.id, 0),
                "transferred_out": out_.get(m.id, 0),
                "transferred_in": in_.get(m.id, 0),
                "closing": c,
            }
        )

    # 已出账的单子用**当初冻结的那份**转账方案 —— 那才是真发到群里、大家照着转的钱。
    # 事后改了这张单子上的账，差额走下一张的「上期结转」，历史方案不该跟着变：
    # 方案一变，「已收到」的勾（按方案下标对位）就会对到别的行上去。
    simplify = bool(settings_svc.get(session, "simplify_debts"))
    frozen_plan = (statement.snapshot_json or {}).get("transfers") if statement else None
    if frozen_plan is not None:
        transfers: list[Transfer] = [Transfer(**t) for t in frozen_plan]
    else:
        transfers = (
            plan_simplified(closing)
            if simplify
            else plan_pairwise(_pair_debts(session, statement))
        )

    # 「**此刻**该谁给谁多少」—— 和「未出账」那页看到的是同一份。
    #
    # 已出账那张单子上的每人行和转账方案说的都是**出账那一刻**的事（方案还是冻结的），
    # 这是对的：账单是一份历史陈述。但界面上最显眼的那句大字和「确认已完成」按钮
    # 是**行动指示**，它们必须按现在的实际情况说话。不这么分开的话：
    #   * 钱已经还清的人，屏幕照样命令他「你要给 Zen ¥9,999」—— 他真会再转一次；
    #   * 出账之后大家换了条路结清（现金、并单转、经第三人），冻结方案里那一对
    #     再也不会走钱，而按钮还亮着 —— 按一下就是凭空造一笔债。
    # 更早那些单子已经靠「收掉按钮」堵住了，最新那张漏了，而最新那张恰恰是
    # 出完账默认停的那一页。
    #
    # 草稿那页的每人行和方案本来就是实时的（它覆盖全部账目），别再算一遍。
    if statement is None:
        live_closing, live_transfers = closing, transfers
    else:
        live_closing = live_balances or {}
        live_transfers = (
            plan_simplified(live_closing)
            if simplify
            else plan_pairwise(_pair_debts(session, None))
        )

    dates = [e.date for e in entries]
    ref = statement.cut_at if statement else now_utc()
    # LIMIT 1：原来不带，把之前的每一张单子连快照 JSON 一起全取出来，只用第一张
    prev = session.exec(
        select(Statement).where(Statement.cut_at < ref).order_by(Statement.cut_at.desc()).limit(1)
    ).first()
    # 刚出过账又出一张，多半是临时结的小账，固定费还没到下一轮 —— 默认别带上。
    # 阈值在设置里，代码只认这个数怎么用。
    # 「上一轮」按**结过固定费的那一张**算：月中结过一次日常小账（不含固定费）的话，
    # 拿它来量，月底那次正经出账就会因为「才过了几天」默认不含固定费。
    # 上一张本身就结了固定费（绝大多数时候）就是它，不用再查一遍
    if prev is None or (prev.snapshot_json or {}).get("include_monthly", True) is not False:
        prev_monthly = prev
    else:
        prev_monthly = _last_monthly_cut(session, before=ref)
    # 按 JST 的**自然日**数，不是 24 小时整段。昨晚 23 点出的账、今天上午再出一张，
    # 整段算只有 0.5 天 → 0 天，会让「包括固定费」在该勾的时候默认不勾
    gap_days = (jst_date(ref) - jst_date(prev_monthly.cut_at)).days if prev_monthly else None
    threshold = int(settings_svc.get(session, "monthly_gap_days"))
    return {
        "prev_cut_at": prev.cut_at.isoformat() if prev else None,
        "prev_label": prev.label if prev else None,
        "days_since_prev_cut": gap_days,
        "suggest_monthly": gap_days is None or gap_days >= threshold,
        "statement_id": statement.id if statement else None,
        "label": statement.label if statement else None,
        "is_draft": statement is None,
        "cut_at": statement.cut_at.isoformat() if statement else None,
        # 起始日 ＝ **上一次出账那天**，不是这张单子里最早那笔的日期。
        # 「7 月那张从 7/2 开始」是错觉 —— 7/1 没人花钱而已，它管的是
        # 6/30 出账之后的一切。头一张没有上一次，只能从第一笔算起。
        # 一笔都没有就是**什么都没覆盖**，两端一起留空。
        # 只给 from 不给 to 的话，界面上会显示成「2026-09-22 〜 」这样断一截
        "covers_from": _covers_from(prev, dates),
        "covers_to": max(dates).isoformat() if dates else None,
        "total_expense": total_expense,
        "total_income": total_income,
        "entry_count": len(entries),
        "members": rows,
        "transfers": [t._asdict() for t in transfers],
        # 行和方案是**历史**，下面这两个是**此刻** —— 大字、进度、按钮都归它们管
        "live_closing": live_closing,
        "live_transfers": [t._asdict() for t in live_transfers],
        "simplified": simplify,
        # 出账之后又被改过的话要说出来，否则下一张的「上期结转」没人解释得清
        "edited_after_cut": _edited_after_cut(session, statement, rows, total_expense),
        # 已出的账单上「本期固定费」列哪几项（没记钱的按 ¥0 列）。草稿那页有自己的面板
        "monthly_ids": billed_monthly_ids(session, statement) if statement is not None else None,
        # 这张单子上的转账记完了没有 —— 「转账按钮都点过了就显示结清」
        **settlement_progress(session, statement),
    }


def billed_monthly_ids(session: Session, statement: Statement) -> list[int]:
    """一张出过的账单上，「本期固定费」列哪几项 —— **没记钱的也列，按 ¥0**。

    只列有钱的那几项的话，出账前面板上是五行、出账后只剩一行：两页同一块
    高低不一，而且「燃气那期没填」和「燃气那期不存在」看上去一模一样。
    清单在出账那一刻记进快照（cut_statement）；这个标记之前出的老账单按现在的
    固定费清单列。没结固定费的那种小账（include_monthly=False）一项都不列。
    """
    snap = statement.snapshot_json or {}
    if "monthly_ids" in snap:
        return list(snap["monthly_ids"])
    if snap.get("include_monthly", True) is False:
        return []
    rows = session.exec(
        select(Category)
        .where(Category.monthly == True, Category.archived == False)  # noqa: E712
        .order_by(Category.display_order, Category.id)
    )
    return [c.id for c in rows]


def _last_monthly_cut(session: Session, before: dt.datetime | None = None) -> Statement | None:
    """最近一张**结了固定费**的账单 —— 出账时没选「不含固定费」的那种。

    「不含固定费」的小账不是一期的边界：固定费那一轮该从哪天算、本期删掉的
    固定费算不算「本期删的」，都得从结了固定费的那一张量起。
    判据是出账时记进快照的 include_monthly；这个标记之前出的老账单一律当完整出账。
    账单一年十来张，逐张看快照比写 JSON 查询省事也好读。
    """
    # 在 SQL 里挑，LIMIT 1。原来是把每一张连快照整个取出来在 Python 里一张张看
    stmt = select(Statement).where(
        func.coalesce(func.json_extract(Statement.snapshot_json, "$.include_monthly"), 1) != 0
    )
    if before is not None:
        stmt = stmt.where(Statement.cut_at < before)
    return session.exec(stmt.order_by(Statement.cut_at.desc()).limit(1)).first()


def _pair_debts(session: Session, statement: Statement | None) -> dict[tuple[int, int], int]:
    """逐对债权，用于「按原始债权结算」：谁垫的钱就还给谁。

    覆盖范围 ＝ 这张账单**自己的**账目 ＋ 它之前出过账的全部账目（草稿就是全部）。
    和 _opening 一样走 SQL 聚合：原来这里把同一批 share 又整个捞了第二遍
    （_opening 一遍、这里一遍），5 年数据下光这一处就是 78ms。
    """
    ids = _earlier_ids(session, statement)

    def scope(stmt):
        stmt = stmt.where(Entry.deleted_at.is_(None))
        if statement is None:
            return stmt                                  # 草稿：出过账的 + 没出账的，全算
        if ids:
            return stmt.where(
                or_(Entry.statement_id == statement.id, Entry.statement_id.in_(ids))
            )
        return stmt.where(Entry.statement_id == statement.id)

    debts: dict[tuple[int, int], int] = {}
    rows = session.exec(
        scope(
            select(EntryShare.member_id, Entry.payer_id, func.sum(EntryShare.amount_jpy))
            .join(Entry, Entry.id == EntryShare.entry_id)
            .where(Entry.kind != EntryKind.settlement)
        ).group_by(EntryShare.member_id, Entry.payer_id)
    )
    for member_id, payer_id, total in rows:
        if member_id == payer_id or not total:
            continue
        key = (member_id, payer_id)
        debts[key] = debts.get(key, 0) + int(total)

    # 转账反向抵消：A 转给 B，就是 B 对 A 的债权少了这么多
    paid = session.exec(
        scope(
            select(Entry.to_member_id, Entry.payer_id, func.sum(Entry.amount_jpy)).where(
                Entry.kind == EntryKind.settlement, Entry.to_member_id.is_not(None)
            )
        ).group_by(Entry.to_member_id, Entry.payer_id)
    )
    for to_id, payer_id, total in paid:
        key = (to_id, payer_id)
        debts[key] = debts.get(key, 0) + int(total or 0)

    return {k: v for k, v in debts.items() if v}


def _edited_after_cut(
    session: Session, statement: Statement | None, rows: list[dict[str, Any]], live_total: int
) -> dict[str, Any] | None:
    """这张账单出完之后，数字还是不是当初那份。

    不锁定历史（余额全局累计，改了也不会算错钱），但**必须让改动可见** ——
    否则下一张账单上冒出来的「上期结转」没人解释得清。

    两种都要认：
      * 改的是**这张单子上的账** —— 合计当场变了
      * 改的是**更早那张单子上的账** —— 这张一笔没动，可「上期结转」跟着变，
        于是每个人的结余都不一样了。只盯前一种的话，六月的账单会在七月的
        账被改之后悄悄换一组数字，而它上面什么提示都没有
    """
    if statement is None:
        return None
    # **一条聚合，不要逐条 get。** 原来是把 `at > cut_at` 的审计日志整行捞出来
    # （只用得上 target_id，却把 before_json/after_json 两个 JSON blob 一起反序列化），
    # 再对每一条调两次 `session.get(Entry, ...)` —— 两次不会被 identity map 挡掉：
    # 它存的是**弱引用**，推导式里第一次 get 的返回值当场没人持有就被回收了。
    # 5 年规模的库上实测 503 次 SQL / 71ms，而且随「改过多少笔账」无上界地涨
    edited = select(AuditLog.target_id).where(
        AuditLog.target_table == "entry",
        AuditLog.at > statement.cut_at,
        AuditLog.action.in_(["update", "delete", "restore"]),
    )
    n_touched = session.exec(
        select(func.count())
        .select_from(Entry)
        .where(Entry.id.in_(edited), Entry.statement_id == statement.id)
    ).one()

    snapshot = statement.snapshot_json or {}
    frozen_closing = {r["member_id"]: r["closing"] for r in snapshot.get("members", [])}
    live_closing = {r["member_id"]: r["closing"] for r in rows}
    drifted = any(live_closing.get(mid, 0) != c for mid, c in frozen_closing.items())

    if not n_touched and not drifted:
        return None
    return {
        "count": n_touched,
        "frozen_total": snapshot.get("total_expense"),
        # build_bill 手里就有这张的实时合计，不用再把它的账目查一遍
        "live_total": live_total,
        # 这张单子自己一笔没动，是更早那张被改了才漂的
        "from_earlier": not n_touched and drifted,
    }


def list_totals(session: Session) -> dict[int, int]:
    """每张账单的支出合计，一次查完。

    列表页每一行都要这个数。原来是逐张调 build_total_expense，60 张就是 60 次
    全表扫 —— 实测 5 年规模下 /api/statements 要 51ms，而它是**每次打开账单页
    都调**的那个接口。
    """
    rows = session.exec(
        select(Entry.statement_id, func.sum(Entry.amount_jpy))
        .where(
            Entry.deleted_at.is_(None),
            Entry.statement_id.is_not(None),
            Entry.kind == EntryKind.expense,
        )
        .group_by(Entry.statement_id)
    )
    return {sid: int(total or 0) for sid, total in rows}


def list_settled(session: Session, statements: list[Statement]) -> dict[int, bool]:
    """每张账单结清了没有，一次查完。

    判据和 settlement_progress 一模一样（按这张的方案，该给的钱后来给够了没有），
    只是把「每张各查一次转账」换成「转账只查一次，在内存里按张分」——
    转账本来就没几笔，而账单会一直变多。
    """
    if not statements:
        return {}
    # 四列就够，不造 ORM 对象：这个循环是「账单数 × 转账数」，两样都只会越来越多
    rows = list(
        session.exec(
            select(Entry.created_at, Entry.payer_id, Entry.to_member_id, Entry.amount_jpy).where(
                Entry.kind == EntryKind.settlement,
                Entry.deleted_at.is_(None),
                Entry.to_member_id.is_not(None),
            )
        )
    )
    out: dict[int, bool] = {}
    for st in statements:
        plan = (st.snapshot_json or {}).get("transfers") or []
        if not plan:
            out[st.id] = True
            continue
        pairs = {(t["from_id"], t["to_id"]) for t in plan}
        paid: dict[tuple[int, int], int] = {}
        for created, frm, to, amount in rows:
            if created <= st.cut_at:
                continue
            key = (frm, to)
            if key in pairs:
                paid[key] = paid.get(key, 0) + amount
        out[st.id] = all(paid.get((t["from_id"], t["to_id"]), 0) >= t["amount"] for t in plan)
    return out


def build_total_expense(session: Session, statement: Statement) -> int:
    """一张账单的支出合计，逐笔加。列表页走的是 list_totals 那条聚合，这个留给测试对账"""
    return sum(
        e.amount_jpy for e in entries_of(session, statement.id) if e.kind == EntryKind.expense
    )


# ------------------------------------------------------------------ 出账


def cut_statement(
    session: Session,
    *,
    actor_id: int | None,
    label: str | None = None,
    include_monthly: bool = True,
    on: dt.date | None = None,
) -> Statement:
    """出账单：把这一刻之前没出账的账目归到一张单子上，并冻结快照。

    `include_monthly=False` 时**把固定费留在草稿里**，只出日常那部分 ——
    月中想把日用品先结一轮、又不想等水电煤账单的时候用。

    `on` 只给种子/测试用来铺时间线，正常就是今天（JST）。
    """
    entries = unbilled(session)
    monthly_ids = {
        c.id
        for c in session.exec(select(Category).where(Category.monthly == True))  # noqa: E712
    }
    if not include_monthly:
        entries = [e for e in entries if e.category_id not in monthly_ids]
    if not entries:
        raise BillError("nothing_to_cut", "现在没有待出账的账目")

    today = on or today_jst()
    # 固定费不按「哪天填的」记 —— 家賃这种根本没有填入日，它就是这张账单的一项。
    # 出账那一刻统一盖成出账日：账目里一张账单的固定费并成一块，不再散在整个月。
    # 日常开销不动，几号买的日用品是真事。
    for e in entries:
        if e.category_id in monthly_ids:
            e.date = today
            session.add(e)

    dates = [e.date for e in entries]
    # 起始日跟 build_bill 一个口径：上一次出账那天。头一张才从第一笔算起
    prev = session.exec(select(Statement).order_by(Statement.cut_at.desc())).first()
    statement = Statement(
        # **不在这儿拼展示文案。** 拼出来的是简体中文，而它会被写进库里 ——
        # 日文界面上那张账单的标题从此永远是「8/30 出账」，改代码也救不回来。
        # 留空，前端按 cut_at 用 i18n 渲染（src/statement.ts）
        label=label or "",
        cut_at=now_utc(),
        covers_from=dt.date.fromisoformat(_covers_from(prev, dates) or min(dates).isoformat()),
        covers_to=max(dates),
        cut_by=actor_id,
    )
    session.add(statement)
    session.flush()

    # **归期要做成一条带条件的 UPDATE。** 原来是逐条 `e.statement_id = statement.id`，
    # 而 unbilled() 那次 SELECT 根本不在写事务里（pysqlite 读不开事务）：
    # 两次出账重叠时两边读到同一批账目，后提交的把它们全抢走，先出的那张
    # 一笔账都不剩 —— 可它的快照还冻结着全额，从此在列表里挂着 ¥0 / 未结清，
    # 还会当上下一张的 prev，把覆盖期和「固定费默认不带」一起带歪。
    # 手机上出账按钮点两下就够复现。
    # flush() 已经把连接推进写事务，所以这条 UPDATE 自带串行化保证。
    ids = [e.id for e in entries]
    claimed = session.execute(
        sa_update(Entry)
        .where(Entry.id.in_(ids), Entry.statement_id.is_(None))
        # version 跟着 +1：出账前打开的编辑页、固定费面板手里拿的 version 全部作废。
        # 不推进的话它们照样改得进去 —— 改的是一张刚发进群里的账单，而屏幕上以为
        # 自己在改草稿
        .values(statement_id=statement.id, version=Entry.version + 1)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != len(ids):
        # 连同上面那批固定费的日期覆盖一起回滚 —— 那同样是对陈旧行的无条件写
        session.rollback()
        raise BillError("nothing_to_cut", "刚才已经有人出过账了，刷新一下再看")
    session.expire_all()   # bulk UPDATE 绕过了身份映射，手里那份 statement_id 还是旧的

    # 快照里不存结算进度：它是**实时**的（转账是出账之后才发生的），
    # 而快照算在 snapshot_json 还没写入的那一刻，plan 为空会被当成「已结清」，
    # 冻结下来就是个假值，早晚误导人
    snapshot = build_bill(session, statement)
    # settlement_progress 返的每一项都要 pop —— 漏一个就在快照里冻下一份假进度。
    # 加字段的时候很容易只记得改 settlement_progress 忘了改这儿（settled_paid
    # 就是这么漏过一次的），所以这里按它的返回值来，不手抄字段名
    for key in settlement_progress(session, None):
        snapshot.pop(key, None)
    # 这一张结没结固定费。「不含固定费」的小账不是一期的边界（见 _last_monthly_cut）
    snapshot["include_monthly"] = include_monthly
    # 出账那一刻面板上是哪几项：没归档的全部，加上归档了但这张还挂着钱的。
    # 没填的那几项按 ¥0 结，账单上也照样列着（见 billed_monthly_ids）
    with_money = {e.category_id for e in entries if e.category_id in monthly_ids}
    snapshot["monthly_ids"] = [
        c.id
        for c in session.exec(
            select(Category).where(Category.monthly == True).order_by(Category.display_order, Category.id)  # noqa: E712
        )
        if not c.archived or c.id in with_money
    ] if include_monthly else []
    statement.snapshot_json = snapshot
    session.add(statement)
    session.add(
        AuditLog(
            member_id=actor_id,
            action="cut_statement",
            target_table="statement",
            target_id=statement.id,
            after_json={"label": statement.label, "entries": len(entries)},
        )
    )
    session.commit()
    session.refresh(statement)
    return statement


class BillError(ValueError):
    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


# ------------------------------------------------- 「确认已完成」

#: 「算此刻还差多少 → 记账」必须是一步。服务是单进程（README 部署那一行），
#: 一把进程内的锁就够 —— 和 _carry_lock 同一个做法
_confirm_lock = threading.Lock()


def pair_left(session: Session, statement: Statement | None, from_id: int, to_id: int) -> int:
    """这张单子上 from → to 那一笔**此刻**还该转多少。和前端 BillView 的 leftOf 同一口径：

      * 「这一笔还剩多少」＝ 方案额 − 出账后已经转过的；
      * 「这一对此刻还欠多少」＝ 实时方案里同一对的金额，**不在实时方案里就是 0** ——
        出账之后大家换了条路结清（现金、并单转、经第三人），这一对就再也不会走钱。
    两头取小。方案里没有这一对也是 0。
    """
    b = build_bill(session, statement)
    for i, t in enumerate(b["transfers"]):
        if t["from_id"] == from_id and t["to_id"] == to_id:
            paid = b["settled_paid"][i] if i < len(b["settled_paid"]) else 0
            live = next(
                (x["amount"] for x in b["live_transfers"] if x["from_id"] == from_id and x["to_id"] == to_id),
                0,
            )
            return max(0, min(t["amount"] - paid, live))
    return 0


def confirm_transfer(
    session: Session,
    *,
    statement: Statement | None,
    from_id: int,
    to_id: int,
    amount: int,
    expect_left: int,
    on: dt.date,
    actor_id: int | None,
) -> Entry:
    """在账单上点「确认已完成」＝ 记一笔 from → to 的转账。

    原来前端直接 POST 一笔转账，后端什么都不查：转出方和转入方**各点一次**
    （两个人都觉得该由自己来点），或者对话框的「确定」被连点两下，
    账本里就多出一笔一模一样的钱 —— 实测 B 从欠 10,000 变成倒被欠 9,000。

    现在前端要带上「我打开对话框时看到还差多少」（expect_left）。锁里按同一口径
    重算，**对不上就不记**：有人刚记过一笔（或者另一台设备刚点过），
    这边拿到 409 和新的数，重取之后让人自己看一眼。金额本身不设上限 ——
    真多转了就该照实记，差额自然成了反方向的债。
    """
    with _confirm_lock:
        left = pair_left(session, statement, from_id, to_id)
        if left != expect_left:
            raise BillError("transfer_changed", "transfer progress changed", left=left)
        if left == 0:
            raise BillError("transfer_changed", "nothing left to transfer", left=0)
        return ledger.create_entry(
            session,
            actor_id=actor_id,
            kind=EntryKind.settlement,
            on=on,
            amount=amount,
            payer_id=from_id,
            to_member_id=to_id,
        )


# ------------------------------------------------- 当前草稿账单上的「固定费」


def monthly_rows(session: Session, statement: Statement | None = None) -> dict[str, Any]:
    """每月一次的固定项在某张账单里的状态。statement 传 None ＝ 当前草稿。

    **没录的就是没录，amount 给 None**，界面上是个空框，出账时按 0 算。
    这里不给「上次记了多少」当参考：要每期照抄的项，去分类上开 `same_as_last`，
    再由人在那一行上点「照上期」（carry_same_as_last）记成**真值**（黑字，看得见）。
    """
    # 翻历史账单时**连归档的也要列**：那张单子上真有这笔钱，总额里也算着它。
    # 只按「现在还没归档」过滤的话，归档一个分类会让它名下的旧账凭空消失，
    # 而账单合计不变 —— 一眼看去就是「这几项加不出总数」
    stmt = select(Category).where(Category.monthly == True)  # noqa: E712
    categories = list(session.exec(stmt.order_by(Category.display_order, Category.id)))
    # 草稿里的账这一趟要用三次（占位、合计、「和上期一样」），只查一次
    draft = unbilled(session) if statement is None else None
    if draft is not None:
        # 草稿里归档的项默认不占位（归档＝以后不用填了），但**它名下本期已经录了钱的
        # 除外**：那笔钱还在账单的合计和每人应担里，面板上却一行都看不见，
        # 于是同一张草稿出现两个对不上的合计，而且那笔钱既改不了也删不掉
        with_money = {e.category_id for e in draft if e.category_id is not None}
        categories = [c for c in categories if not c.archived or c.id in with_money]
    # 同一个分类在这张草稿里可能有不止一笔（两个人同时填、或者填完重试了一次）。
    # 面板一行只显示得下一笔，**但账单是全都算的** —— 不把重复说出来的话，
    # 用户看到「家賃 170,000」，完全不知道还有一笔 120,000 也在总额里。
    mine: dict[int, Entry] = {}
    dup: dict[int, int] = {}
    monthly_ids = {c.id for c in categories}
    total = 0
    for e in (draft if draft is not None else entries_of(session, statement.id)):  # type: ignore[union-attr]
        if e.kind == EntryKind.settlement or e.category_id is None:
            continue
        mine[e.category_id] = e
        dup[e.category_id] = dup.get(e.category_id, 0) + 1
        if e.category_id in monthly_ids:
            total += e.amount_jpy
    # 草稿里还没录的行：垫付人和分摊从**上期那一笔**起步，和「和上期一样」同一个口径
    # （SPEC F1：分摊规则默认＝该分类上次用的规则）。原来是分类默认规则 ——
    # 而界面上改房租怎么分只能逐笔改，于是每期手填一次房租，分摊就打回均分一次。
    # 人变了（有人搬走/搬进来）就不抄：退回分类默认，由人自己重新定
    last = _last_billed(session, [c.id for c in categories]) if statement is None else {}
    active = {m.id for m in ledger.active_members(session, today_jst())} if statement is None else set()
    # 「和上期一样」这一步现在要人点（面板上那个按钮、出账时那个勾），
    # 所以得先告诉界面：点下去会记哪几项、多少钱，哪几项记不了
    ready: dict[int, int] = {}
    blocked: dict[int, str] = {}
    if draft is not None:
        todo, failed = _carry_plan(session, draft)
        ready = {c.id: prev.amount_jpy for c, prev, _, _ in todo}
        blocked = {f["category_id"]: f["reason"] for f in failed}
    rows = []
    for c in categories:
        entry = mine.get(c.id)
        prev = last.get(c.id)
        seed = c.default_rule_json
        prev_payer = None
        if prev is not None:
            if prev.split_rule_json and _stale_for_today(prev.split_rule_json, None, active) is None:
                seed = _prune_rule(prev.split_rule_json, active)
            prev_payer = prev.payer_id if prev.payer_id in active else None
        # 翻一张已经出过的账单时只列它真有的那几项。空行会诱人往里填，
        # 而填出来的是**新账目**，落进当前草稿，根本不会进这张单子。
        if statement is not None and entry is None:
            continue
        rows.append(
            {
                "category_id": c.id,
                "name": c.name,
                "icon": c.icon,
                "color": c.color,
                #: 已经删掉（归档）但本期还挂着钱的那种。界面要明说，
                #: 否则「点了删除这一行还在」看上去就是没删掉
                "archived": c.archived,
                "default_rule_json": c.default_rule_json,
                #: 这一项默认谁垫。面板据此预填「谁付的」，不再是「谁填的算谁」
                "default_payer_id": c.default_payer_id,
                #: 每期金额都一样 —— 打开的话出账前会自动按上期金额记上
                "same_as_last": c.same_as_last,
                "entry_id": entry.id if entry else None,
                "amount": entry.amount_jpy if entry else None,
                "version": entry.version if entry else None,
                "rule": entry.split_rule_json if entry else seed,
                #: 上期那一笔是谁垫的（还在籍才给）。面板上没录的行按它预填「谁付的」
                "last_payer_id": prev_payer,
                "date": entry.date.isoformat() if entry else None,
                #: 本期这个分类一共有几笔。>1 说明面板没显示全，界面上必须提示
                "entry_count": dup.get(c.id, 0),
                #: 按「和上期一样」点一下会记多少（只有草稿、开了开关、本期还没处理过的才有）
                "carry_amount": ready.get(c.id),
                #: 开了开关却记不了的原因（payer_left / rule_stale），要人自己填
                "carry_blocked": blocked.get(c.id),
            }
        )

    return {
        "default_date": today_jst().isoformat(),
        "rows": rows,
        # 面板一行只显示得下一笔，所以合计**不能由行加出来** —— 同一分类有两笔时
        # 会少算一笔，而账单上的「本期固定费」是全算的，两个数当场对不上
        "total": total,
    }


#: carry 这件事整个进程里一次只许跑一个。
#: 「读一遍本期已经有哪几项 → 把缺的记上」中间隔着好几十毫秒。原来触发它的是
#: 账单页挂载 —— 群里一句「出账了」，三个人同时点开，两个请求都在对方 commit
#: 之前读到「本期还没记房租」，于是各记一笔，当期房租翻倍。现在改成人点按钮了，
#: 可两个人同时点、或者一个人连点照样会撞，锁留着。
#: 面板一行只显示得下一笔，屏幕上的金额还是对的、合计却是两倍。
#: 服务是单端口单进程（见 main.py 的 _daily_backup），一把进程内的锁就够；
#: 不加唯一索引 —— 同一分类手工记两笔是合法的（entry_count 就是为它准备的）
_carry_lock = threading.Lock()


def carry_same_as_last(
    session: Session, *, actor_id: int | None, only: set[int] | None = None
) -> dict[str, Any]:
    """把「和上期一样」的固定费按上期金额记进当前草稿。

    **只动明确开了这个开关的项**。默认全是关的：「上次的金额只作灰色占位」
    这条规矩就是为了防「某个月忘了改，带着上月的电费把账单发出去」——
    电费燃气水费恰恰每期都不一样，给它们开这个等于把那条规矩废掉。

    已经录过的一律不碰；从来没出过账的（没有上期金额可抄）跳过。
    **本期手动删掉的也不碰** —— 否则每点一次就复活一次，用户删不掉。
    `only` 给了就只记这几个分类（面板上列出来的那几项）。

    返回 `{"created": [...], "failed": [...]}`：记了哪几笔要说出来（自动记的钱
    必须看得见），**搬不过来的也要说出来**（「自动记账已经停了」同样必须看得见）。
    每一项各自兜错：原来是整个循环一把梭，中间任何一笔抛异常，
    前面那几笔**已经 commit 进草稿了**（create_entry 自己 commit），
    而返回值随异常一起丢掉、接口返 400、前端一个空 catch 吞掉 ——
    屏幕上那几行还是空框，用户照着空框再填一遍，同一分类当期就有了两笔。
    """
    with _carry_lock:
        return _carry(session, actor_id=actor_id, only=only)


def _carry_plan(
    session: Session, draft: list[Entry] | None = None
) -> tuple[list[tuple[Category, Entry, int | None, dict[str, Any] | None]], list[dict[str, Any]]]:
    """算一遍「和上期一样」**现在点下去**会记哪几项。不写库。

    返回 (要记的, 记不了的)。要记的每项是 (分类, 上期那一笔, 垫付人, 分摊规则)。
    面板预览和真正去记走的是同一个函数 —— 按钮上写的和点下去记的不会是两份口径。
    """
    categories = list(
        session.exec(
            select(Category).where(
                Category.monthly == True,  # noqa: E712
                Category.archived == False,  # noqa: E712
                Category.same_as_last == True,  # noqa: E712
            )
        )
    )
    if not categories:
        return [], []

    # 「本期已经处理过」＝ 录了 **或者** 手动删掉了。
    # 只看 unbilled() 的话删掉的那笔不在里面，下次一点又给它记回来。
    #
    # 「本期」要按**上次出账那一刻**卡：草稿里删掉的账目 statement_id 恒为 NULL，
    # 光看这一条的话，半年前删过一次的分类会从此**永远**不再自动记 ——
    # 那是另一个方向的静默失效。两条一起才圈得出「这一期手动删掉的」。
    # draft：调用方手里已经有草稿就递进来（monthly_rows），别再查一遍
    handled = {e.category_id for e in (unbilled(session) if draft is None else draft) if e.category_id is not None}
    # 「上次出账」得是**结过固定费的那一次**。中途出一张「不含固定费」的小账
    # （include_monthly=false）不算一期的边界：拿它当下界的话，它之前那段时间里
    # 手动删掉的房租就不算「本期删的」了，下次一点就被记回来。
    # 判据见 _last_monthly_cut
    since = _last_monthly_cut(session)
    dropped = select(Entry).where(
        Entry.deleted_at.is_not(None),
        Entry.category_id.is_not(None),
        # 而且必须是**草稿里**删的。已出账的账目软删之后 statement_id 还留着，
        # 少了这一条的话，「事后回去修一笔去年的房租」会被当成「本期删掉了房租」，
        # 整个月的房租从此不自动记，面板上就是个空框，出账时按 0 结
        Entry.statement_id.is_(None),
    )
    if since is not None:
        dropped = dropped.where(Entry.deleted_at > since.cut_at)
    handled |= {e.category_id for e in session.exec(dropped)}
    last = _last_billed(session, [c.id for c in categories])
    active = {m.id for m in ledger.active_members(session, today_jst())}

    todo: list[tuple[Category, Entry, int | None, dict[str, Any] | None]] = []
    failed: list[dict[str, Any]] = []
    for c in categories:
        prev = last.get(c.id)
        if c.id in handled or prev is None or not prev.amount_jpy:
            continue
        # **「和上期一样」就是字面意思：金额、分摊、垫付人都照上期那一笔。**
        #
        # 原来只抄金额，分摊用分类默认、垫付人回退到「全局默认 → 当前这个人」：
        #   * 分摊：界面上改房租怎么分只有一条路 —— 在固定费面板里展开那一行改，
        #     改的是那一笔、不是分类。于是「Go 多担 5,000」下一期被悄悄打回均分，
        #     以后每期都是；
        #   * 垫付人：分类和全局都没设时，谁触发了 carry，房租就记成谁垫的。
        # 分类上明写了默认垫付人的仍然优先 —— 那是面板上「谁付的」显式定下的常驻值
        # （改它会同时写分类和那一笔）。SPEC F1：分摊规则默认＝该分类上次用的规则
        payer = c.default_payer_id or prev.payer_id
        rule = prev.split_rule_json or c.default_rule_json
        stale = _stale_for_today(rule, payer, active)
        if stale is not None:
            # 自动记的钱必须看得见 —— 这一条也包括「这次没敢替你记」
            failed.append({"category_id": c.id, "name": c.name, "reason": stale})
            continue
        todo.append((c, prev, payer, _prune_rule(rule, active)))
    return todo, failed


def _carry(session: Session, *, actor_id: int | None, only: set[int] | None) -> dict[str, Any]:
    todo, failed = _carry_plan(session)
    if only is not None:
        # 按钮上列了哪几项就只记哪几项：点的那一刻有一行正在手填，
        # 它不在按钮上写着，就不该被记 —— 否则手填的那笔一存，同一项就是两笔
        todo = [t for t in todo if t[0].id in only]
        failed = [f for f in failed if f["category_id"] in only]
    made: list[dict[str, Any]] = []
    for c, prev, payer, rule in todo:
        try:
            entry = ledger.create_entry(
                session,
                actor_id=actor_id,
                kind=EntryKind.expense,
                on=today_jst(),
                amount=prev.amount_jpy,
                payer_id=payer,
                category_id=c.id,
                rule=rule,
            )
        except (ValueError, KeyError) as e:   # LedgerError / RuleError / SplitError 都是 ValueError
            session.rollback()
            failed.append({"category_id": c.id, "name": c.name, "reason": str(e)})
            continue
        made.append({"category_id": c.id, "name": c.name, "amount": entry.amount_jpy})
    return {"created": made, "failed": failed}


def _stale_for_today(rule: dict[str, Any] | None, payer: int | None, active: set[int]) -> str | None:
    """这一项还能不能照上期自动记？返回拦下来的原因，None ＝ 可以记。

    「和上期一样」抄的是**上一期**的安排，而人是会搬走搬进来的。两件事一旦发生，
    照抄就从「省事」变成「静悄悄记错钱」：

      * **垫付人搬走了** —— 记出来是「已经不住这儿的人又垫了一次房租」，
        账单反过来叫留下的两个人给他转账；
      * **有人新搬进来、而这条规则点名写了谁分多少** —— expand 的口径是
        「规则里没提到的人按 0 补齐」（rules.py），新室友于是白住一个月，
        黑字入账、一句提示都没有。而 _prune_rule 恰好把本来会抛出来的
        unknown_member 消掉了，所以连报错都不会有。

    两种都该**响一声**让人自己重新定，而不是替他记一笔错的 ——
    这跟这个函数「搬不过来的也要说出来」的既有约定是同一条。
    """
    if payer is not None and payer not in active:
        return "payer_left"
    rule = rule or {}
    named = rule.get("exact") if rule.get("mode", "ratio") == "exact" else rule.get("weights")
    if isinstance(named, dict) and named:
        listed: set[int] = set()
        for key in named:
            try:
                listed.add(int(key))
            except (TypeError, ValueError):
                continue
        if active - listed:
            return "rule_stale"
    return None


def _prune_rule(rule: dict[str, Any] | None, active: set[int]) -> dict[str, Any] | None:
    """把分类默认规则里**已经不在籍的人**剔掉。

    分类的默认分摊是当年按那时候几个人写死的（房租那条就点名了 adjustments）。
    有人搬走之后，expand() 会拿「今天在籍的人」当参与人，发现规则里多出一个
    不认识的 id，直接抛 unknown_member —— 于是那一行固定费永远存不上，
    「和上期一样」也从此一声不吭地停了。

    剔掉而不是报错：这是一条**为上一期写的**规则，拿它硬套今天的人本来就不对。
    注意剩下的人分摊会变（adjustments 是「先抠掉再按比例分」），所以调整额一并去掉
    的那份钱会回到大家头上 —— 这是唯一说得通的默认，规则本身该由用户重新定。

    **它只管「人少了」。**「人多了」是另一回事，在 _stale_for_today 那儿拦下来 ——
    往这条规则里补一个新人，补多少只有住的人知道。
    """
    if not rule:
        return rule
    out = dict(rule)
    for field in ("weights", "adjustments", "exact"):
        if isinstance(out.get(field), dict):
            out[field] = {k: v for k, v in out[field].items() if int(k) in active}
            if not out[field]:
                out.pop(field)
    # weights 全被剔光时退回「所有在籍成员同权」，别留一条空规则
    if out.get("mode", "ratio") == "ratio" and "weights" not in out:
        out.setdefault("equal_weight", 1)
    return out


def _last_billed(session: Session, category_ids: list[int]) -> dict[int, Entry]:
    """每个分类**上一次出过账的**那一笔。只给「和上期一样」那几项抄。

    按分类回溯而不是只看上一张单子：水费两个月一收，上一张本来就没有它。
    """
    if not category_ids:
        return {}
    # 每个分类只要最新那一笔：窗口函数在 SQL 里挑，一个分类回来一行。
    # 原来是把这几个分类出过账的每一笔全取出来（一年多六十笔、永远只增）再挑第一笔
    rank = (
        func.row_number()
        .over(partition_by=Entry.category_id, order_by=(Entry.date.desc(), Entry.id.desc()))
        .label("rank")
    )
    latest = (
        select(Entry.id, rank)
        .where(
            Entry.category_id.in_(category_ids),
            Entry.deleted_at.is_(None),
            Entry.statement_id.is_not(None),
            # 只抄支出。收入的金额是**负数**，抄过来 carry 以 expense 建账，
            # 当场撞 bad_sign「支出金额要填正数」—— 而那一项的「和上期一样」
            # 从此每次都失败，用户只看到它一直空着
            Entry.kind == EntryKind.expense,
        )
        .subquery()
    )
    rows = session.exec(select(Entry).join(latest, latest.c.id == Entry.id).where(latest.c.rank == 1))
    return {e.category_id: e for e in rows}


def settlement_progress(session: Session, statement: Statement | None) -> dict[str, Any]:
    """这张账单开出来的转账，记完了几笔。

    判据是「按这张单子的方案，该给的钱后来给够了没有」：出账之后记的转账，
    按「谁给谁」配对累加，每一对都够了就算结清 —— 也就是用户说的
    「转账按钮都点过了」。

    **不拿下一张的出账时刻当上界。** 原来是那么写的，于是「拖到下一张出账之后
    才还钱」这条最常见的路径永远点不亮：那张单子的方案是冻结的（钱到账它也不会变），
    settled_transfers 里那一格于是永远是 False。用户看不到任何变化，
    多半会照着屏幕再转一次 —— 这一屏的全部作用就是防这件事。

    代价说清楚：它意味着**旧单子的绿灯会被后来的钱追认**（B 为了还这一期的
    11,000 转过去，上一期那笔 10,000 也会跟着亮）。债权本来就是全局累计的，
    这个语义说得通；真要更严就得按「这一对之间的净债权是否已清」算，那是另一套。

    只累计 plan 里出现过的那几对：别把下一期新冒出来的别的转账算进这一张。
    """
    if statement is None:
        return {"settled": False, "settled_transfers": [], "settled_paid": []}
    plan = (statement.snapshot_json or {}).get("transfers") or []
    if not plan:
        return {"settled": True, "settled_transfers": [], "settled_paid": []}

    pairs = {(t["from_id"], t["to_id"]) for t in plan}
    rows = session.exec(
        select(Entry).where(
            Entry.kind == EntryKind.settlement,
            Entry.deleted_at.is_(None),
            Entry.created_at > statement.cut_at,
        )
    ).all()

    paid: dict[tuple[int, int], int] = {}
    for e in rows:
        if e.to_member_id is None:
            continue
        key = (e.payer_id, e.to_member_id)
        if key not in pairs:
            continue
        paid[key] = paid.get(key, 0) + e.amount_jpy

    # 顺手把「已经转了多少」也给出去：界面要拿它算「还差多少」。
    # 原来只给一个布尔，于是部分还款之后「确认已完成」还预填全额，
    # 再按一次就重复记了一整笔
    amounts = [paid.get((t["from_id"], t["to_id"]), 0) for t in plan]
    done = [amounts[i] >= t["amount"] for i, t in enumerate(plan)]
    return {"settled": all(done), "settled_transfers": done, "settled_paid": amounts}

