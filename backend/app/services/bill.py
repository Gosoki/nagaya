"""月度账单 —— SPEC F6 / §4.6。

账单只负责**展示**，不参与算钱：余额是全局累计的，账单把它拆成
「期初结转 + 本期发生 + 本期已收付」三段给人看。

    closing = opening + (已垫付 − 应担) + (转出 − 转入)

所以一个人可以同时对两期都有余额（9 月没结完、10 月又开了），
账单照样对得上 —— 这正是「赊账」不需要额外机制的原因。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from app.core.settle import Transfer, plan_pairwise, plan_simplified
from app.models import Entry, EntryKind, EntryShare, Member, Period, PeriodStatus
from app.services import settings as settings_svc


def _entries_of(session: Session, period_id: int) -> list[Entry]:
    return list(
        session.exec(
            select(Entry)
            .where(Entry.period_id == period_id, Entry.deleted_at.is_(None))
            .order_by(Entry.date, Entry.id)
        )
    )


def _shares_of(session: Session, entry_ids: list[int]) -> dict[int, dict[int, int]]:
    """{entry_id: {member_id: 份额}}"""
    if not entry_ids:
        return {}
    rows = session.exec(select(EntryShare).where(EntryShare.entry_id.in_(entry_ids))).all()
    out: dict[int, dict[int, int]] = {}
    for r in rows:
        out.setdefault(r.entry_id, {})[r.member_id] = r.amount_jpy
    return out


def _periods_before(session: Session, period: Period) -> list[int]:
    return [
        p.id
        for p in session.exec(select(Period).where(Period.start_date < period.start_date))
    ]


def _net_of(session: Session, period_ids: list[int]) -> dict[int, int]:
    """给定账期集合里，每个人的净变化（＝付出 − 应担）。"""
    if not period_ids:
        return {}
    entries = list(
        session.exec(
            select(Entry).where(
                Entry.period_id.in_(period_ids), Entry.deleted_at.is_(None)
            )
        )
    )
    shares = _shares_of(session, [e.id for e in entries])
    net: dict[int, int] = {}
    for e in entries:
        net[e.payer_id] = net.get(e.payer_id, 0) + e.amount_jpy
        for m, s in shares.get(e.id, {}).items():
            net[m] = net.get(m, 0) - s
    return net


def _pair_debts(session: Session, period_ids: list[int]) -> dict[tuple[int, int], int]:
    """逐对债权：debt[(欠钱的, 垫钱的)] = 金额。用于「按原始债权结算」。"""
    entries = list(
        session.exec(
            select(Entry).where(
                Entry.period_id.in_(period_ids), Entry.deleted_at.is_(None)
            )
        )
    )
    shares = _shares_of(session, [e.id for e in entries])
    debts: dict[tuple[int, int], int] = {}
    for e in entries:
        if e.kind == EntryKind.settlement:
            # 还钱：收钱的人对垫钱的人的欠额增加，正好和原来的债抵消
            if e.to_member_id is not None:
                key = (e.to_member_id, e.payer_id)
                debts[key] = debts.get(key, 0) + e.amount_jpy
            continue
        for m, s in shares.get(e.id, {}).items():
            if m == e.payer_id or s == 0:
                continue
            key = (m, e.payer_id)
            debts[key] = debts.get(key, 0) + s
    return debts


def build_bill(session: Session, period: Period) -> dict[str, Any]:
    entries = _entries_of(session, period.id)
    shares = _shares_of(session, [e.id for e in entries])
    members = list(session.exec(select(Member).order_by(Member.display_order, Member.id)))

    before = _periods_before(session, period)
    opening = _net_of(session, before)

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
        for m, s in shares.get(e.id, {}).items():
            owed[m] = owed.get(m, 0) + s
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

    simplify = bool(settings_svc.get(session, "simplify_debts"))
    if simplify:
        transfers: list[Transfer] = plan_simplified(closing)
    else:
        transfers = plan_pairwise(_pair_debts(session, before + [period.id]))

    # 「含 7–8 月水费」这类标注：只把带计费期间的条目挑出来给前端拼文案
    covers = [
        {
            "entry_id": e.id,
            "title": e.title,
            "category_id": e.category_id,
            "period_start": e.period_start.isoformat() if e.period_start else None,
            "period_end": e.period_end.isoformat() if e.period_end else None,
        }
        for e in entries
        if e.period_start or e.period_end
    ]

    return {
        "period": {
            "id": period.id,
            "label": period.label,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
            "status": period.status.value,
        },
        "settle_due": _settle_due(session, period),
        "total_expense": total_expense,
        "total_income": total_income,
        "entry_count": len(entries),
        "members": rows,
        "transfers": [t._asdict() for t in transfers],
        "simplified": simplify,
        "covers": covers,
    }


def _settle_due(session: Session, period: Period) -> str | None:
    """结算日：账期结束后次月的第 N 天。没设就返回 None，账单只写「未结清」。"""
    day = settings_svc.get(session, "settle_due_day")
    if not day:
        return None
    end = period.end_date
    year, month = (end.year, end.month + 1) if end.month < 12 else (end.year + 1, 1)
    import calendar

    return dt.date(year, month, min(int(day), calendar.monthrange(year, month)[1])).isoformat()


def close_period(session: Session, period: Period, *, actor_id: int | None) -> Period:
    """关账：冻结一份账单快照，之后这一期的明细锁定。

    **允许带着未结清的余额关账** —— 那就是赊账，差额自动结转到下一期。
    """
    if period.status == PeriodStatus.closed:
        return period
    period.snapshot_json = build_bill(session, period)
    period.status = PeriodStatus.closed
    period.closed_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    period.closed_by = actor_id
    session.add(period)
    _log(session, actor_id, "close_period", period)
    session.commit()
    session.refresh(period)
    return period


def reopen_period(session: Session, period: Period, *, actor_id: int | None) -> Period:
    """解锁。快照留着 —— 要能看出「当初出的那张账单长什么样」。"""
    period.status = PeriodStatus.open
    period.closed_at = None
    period.closed_by = None
    session.add(period)
    _log(session, actor_id, "reopen_period", period)
    session.commit()
    session.refresh(period)
    return period


def _log(session: Session, actor_id: int | None, action: str, period: Period) -> None:
    from app.models import AuditLog

    session.add(
        AuditLog(
            member_id=actor_id,
            action=action,
            target_table="period",
            target_id=period.id,
            after_json={"label": period.label, "status": period.status.value},
        )
    )
