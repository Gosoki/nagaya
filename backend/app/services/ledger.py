"""账本核心操作 —— 记一笔、归期、算余额。

这里是唯一允许写 entry_share 的地方。别处要算钱，一律读快照。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Sequence

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.period import period_bounds, period_label
from app.core.rules import expand, mkey, participants, pick_rule
from app.core.split import split
from app.models import (
    AuditLog,
    Entry,
    EntryKind,
    EntryShare,
    Member,
    Period,
    PeriodStatus,
    now_utc,
    today_jst,
)
from app.services import settings as settings_svc


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


# ------------------------------------------------------------------ 账期


def get_or_create_period(session: Session, on: dt.date) -> Period:
    """取 on 这天所属的账期，没有就建。"""
    start_day = int(settings_svc.get(session, "period_start_day"))
    start, end = period_bounds(on, start_day)
    row = session.exec(select(Period).where(Period.start_date == start)).first()
    if row is None:
        row = Period(label=period_label(end), start_date=start, end_date=end)
        session.add(row)
        session.flush()
    return row


def oldest_open_period(session: Session) -> Period | None:
    return session.exec(
        select(Period).where(Period.status == PeriodStatus.open).order_by(Period.start_date)
    ).first()


def assign_period(session: Session, kind: EntryKind, on: dt.date) -> Period:
    """这笔账算哪一期。

    * 支出 / 收入 —— 按**发生日**归期（SPEC §4.6）
    * 转账 —— 挂到**最早的未关账账期**，因为你还的就是那一期的账。
      这正是「10/15 记的转账要算进 9 月期」那条规则的落点：光看日期推不出来，
      所以显式存 entry.period_id，而不是查询时现猜。

    账期已关账的话拒绝写入 —— 账本最忌讳的就是钱悄悄挪到别的月份去。
    """
    if kind == EntryKind.settlement:
        target = oldest_open_period(session) or get_or_create_period(session, on)
    else:
        target = get_or_create_period(session, on)
    if target.status == PeriodStatus.closed:
        raise LedgerError(
            "period_closed",
            f"{target.label} 期已关账，要改先解锁",
            period_id=target.id,
            label=target.label,
        )
    return target


# ------------------------------------------------------------------ 记一笔


def _validate_amount(kind: EntryKind, amount: int) -> None:
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise LedgerError("not_integer", f"金额必须是整数日元，收到 {amount!r}")
    if amount == 0:
        raise LedgerError("zero_amount", "金额不能是 0")
    if kind == EntryKind.expense and amount < 0:
        raise LedgerError("bad_sign", "支出金额要填正数；退款/返现请记成「收入」")
    if kind == EntryKind.income and amount > 0:
        raise LedgerError("bad_sign", "收入金额存为负数（返现是大家一起收的钱）")
    if kind == EntryKind.settlement and amount < 0:
        raise LedgerError("bad_sign", "转账金额要填正数；方向反了就把转出/转入对调")


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
    period_start: dt.date | None = None,
    period_end: dt.date | None = None,
    bundle_id: int | None = None,
) -> Entry:
    """记一笔，并把分摊结果**固化**成 entry_share。

    分摊只在这一刻算一次。之后改默认比例、加成员、删分类，这条账都不会变。
    """
    _validate_amount(kind, amount)
    period = assign_period(session, kind, on)

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
        period_id=period.id,
        period_start=period_start,
        period_end=period_end,
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


def _write_shares(session: Session, entry: Entry, expanded: dict[str, Any], payer_id: int) -> None:
    """算分摊 → 断言合计 → 落库。entry_share 只在这里被写。"""
    order = participants(expanded)
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


def _guard_period(session: Session, entry: Entry) -> None:
    """已关账的账目不许动。"""
    if entry.period_id is None:
        return
    period = session.get(Period, entry.period_id)
    if period is not None and period.status == PeriodStatus.closed:
        raise LedgerError(
            "period_closed",
            f"{period.label} 期已关账，要改先解锁",
            period_id=period.id,
            label=period.label,
        )


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
    if entry.version != version:
        raise LedgerError(
            "version_conflict",
            "这笔账刚被人改过，请刷新后重试",
            expected=entry.version,
            got=version,
        )
    _guard_period(session, entry)
    before = _snapshot(session, entry)

    for key in ("title", "note", "category_id", "period_start", "period_end", "bundle_id"):
        if key in fields:
            setattr(entry, key, fields[key])

    amount = fields.get("amount_jpy", entry.amount_jpy)
    kind = fields.get("kind", entry.kind)
    on = fields.get("date", entry.date)
    payer_id = fields.get("payer_id", entry.payer_id)
    to_member_id = fields.get("to_member_id", entry.to_member_id)
    _validate_amount(kind, amount)

    if on != entry.date or kind != entry.kind:
        period = assign_period(session, kind, on)
        entry.period_id = period.id
    entry.kind, entry.date, entry.amount_jpy = kind, on, amount
    entry.payer_id, entry.to_member_id = payer_id, to_member_id

    if kind == EntryKind.settlement:
        if to_member_id is None:
            raise LedgerError("missing_to_member", "转账必须指定转入人")
        if to_member_id == payer_id:
            raise LedgerError("self_transfer", "不能转给自己")
        expanded = {"mode": "exact", "exact": {mkey(to_member_id): amount}}
    else:
        ids = (
            list(member_ids)
            if member_ids is not None
            else [int(k) for k in participants(entry.split_rule_json)]
            or [m.id for m in active_members(session, on)]
        )
        global_rule = settings_svc.get(session, "default_rule")
        base = rule if rule is not None else (entry.split_rule_json if member_ids is None else None)
        expanded = expand(pick_rule(base, category_rule, global_rule), ids)
        if not expanded.get("remainder_to"):
            expanded["remainder_to"] = settings_svc.get(session, "remainder_to")

    entry.split_rule_json = expanded
    entry.updated_at = now_utc()
    entry.version += 1
    session.add(entry)
    session.flush()

    _write_shares(session, entry, expanded, payer_id)
    _audit(session, actor_id, "update", "entry", entry.id, before, _snapshot(session, entry))
    session.commit()
    session.refresh(entry)
    return entry


def delete_entry(session: Session, entry: Entry, *, actor_id: int | None) -> None:
    """软删，进回收站。分摊快照留着 —— 但余额不再算它。"""
    _guard_period(session, entry)
    before = _snapshot(session, entry)
    entry.deleted_at = now_utc()
    session.add(entry)
    _audit(session, actor_id, "delete", "entry", entry.id, before, None)
    session.commit()


def restore_entry(session: Session, entry: Entry, *, actor_id: int | None) -> None:
    """从回收站捞回来。"""
    _guard_period(session, entry)
    entry.deleted_at = None
    session.add(entry)
    _audit(session, actor_id, "restore", "entry", entry.id, None, _snapshot(session, entry))
    session.commit()
