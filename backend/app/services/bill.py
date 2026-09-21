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
from app.models import (
    Category,
    Entry,
    EntryKind,
    EntryShare,
    Member,
    Period,
    PeriodStatus,
    today_jst,
)
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

    # 「含 7–8 月水费」这类标注。
    # **只收跨期的**：计费期间落在本期之外才算。否则等每一行都能顺手填期间之后，
    # 这句话会变成「含 家賃（10/01〜10/31）· 含 電気（09/01〜09/30）· …」一长串，
    # 把「这个月为什么贵了一万二」这个唯一有用的信号自己淹掉。
    covers = [
        {
            "entry_id": e.id,
            "title": e.title,
            "category_id": e.category_id,
            "period_start": e.period_start.isoformat() if e.period_start else None,
            "period_end": e.period_end.isoformat() if e.period_end else None,
        }
        for e in entries
        if _crosses_period(e, period)
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

    **`snapshot_json` 只在第一次关账时写，之后永不覆盖。**
    快照存在的唯一理由就是「证明当初发给室友的那张账单长什么样」。
    而「关账 → 发现漏录 → 解锁 → 补录 → 再关账」是常规操作，
    要是每次关账都重写快照，室友照着旧账单转了钱、系统里的账单却已经变了，
    就再没有任何东西能还原当时那张。重关的新版进 audit_log，原件不动。
    """
    if period.status == PeriodStatus.closed:
        return period
    fresh = build_bill(session, period)
    if period.snapshot_json is None:
        period.snapshot_json = fresh
        _log(session, actor_id, "close_period", period)
    else:
        _log(session, actor_id, "close_period_again", period,
             before=period.snapshot_json, after=fresh)
    period.status = PeriodStatus.closed
    period.closed_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    period.closed_by = actor_id
    session.add(period)
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


def _log(
    session: Session,
    actor_id: int | None,
    action: str,
    period: Period,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    from app.models import AuditLog

    session.add(
        AuditLog(
            member_id=actor_id,
            action=action,
            target_table="period",
            target_id=period.id,
            before_json=before,
            after_json=after or {"label": period.label, "status": period.status.value},
        )
    )


def _crosses_period(entry: Entry, period: Period) -> bool:
    """这条账目的计费期间是不是真的伸到本账期之外了。

    只有跨出去的才值得在账单上单独标一句（水费两个月一收、家賃前払い）。
    本期内的常规项标了等于噪音。
    """
    for bound in (entry.period_start, entry.period_end):
        if bound is not None and not (period.start_date <= bound <= period.end_date):
            return True
    return False


# ------------------------------------------------- 账单页顶部的「本期固定费」


def _prev_period(session: Session, period: Period) -> Period | None:
    return session.exec(
        select(Period)
        .where(Period.start_date < period.start_date)
        .order_by(Period.start_date.desc())
    ).first()


def default_date_for(period: Period) -> dt.date:
    """在账单页顺手录的账，日期默认取哪天。

    **这是整块设计里最容易出错的地方**：`assign_period()` 按发生日归期，
    所以在 10/10 填 9 月账单时若默认取「今天」，那笔家賃会落进 10 月期 ——
    9 月账单上凭空少一笔，而且零报错。
    所以默认日期必须落在**这张账单自己的期间内**：今天在期内就用今天，
    否则用期末那天。每行仍可单独改，改到期外时前端要当场把算出来的账期显示出来。
    """
    today = today_jst()
    if period.start_date <= today <= period.end_date:
        return today
    return period.end_date


def monthly_rows(session: Session, period: Period) -> dict[str, Any]:
    """每月一次的固定项在本期的状态：已录的给真值，没录的给上期金额做灰色参考。

    「上期金额」**只是占位提示，不是值**。账本里预填的数字很危险：
    长得跟亲手填的一模一样，某个月忘了改就带着上月的数字发出去了，谁都看不出来。
    所以它单独放在 `hint` 里，前端渲染成灰色 placeholder，用户不动它就等于没录。
    """
    categories = list(
        session.exec(
            select(Category)
            .where(Category.monthly == True, Category.archived == False)  # noqa: E712
            .order_by(Category.display_order, Category.id)
        )
    )
    mine = {
        e.category_id: e
        for e in _entries_of(session, period.id)
        if e.kind != EntryKind.settlement and e.category_id is not None
    }

    # 参考值取「**这个分类上一次记的是多少**」，而不是「上一期是多少」。
    # 水费两个月一收，上一期本来就没有；中间还可能夹着一个空账期
    # （账目删光了但期还在）。按分类回溯才是人真正想看的那个数。
    prev_amounts, prev_labels = _last_amount_before(
        session, [c.id for c in categories], period.start_date
    )

    rows = []
    for c in categories:
        entry = mine.get(c.id)
        rows.append(
            {
                "category_id": c.id,
                "name": c.name,
                "icon": c.icon,
                "color": c.color,
                "default_rule_json": c.default_rule_json,
                "entry_id": entry.id if entry else None,
                "amount": entry.amount_jpy if entry else None,
                "version": entry.version if entry else None,
                "rule": entry.split_rule_json if entry else c.default_rule_json,
                "period_start": entry.period_start.isoformat() if entry and entry.period_start else None,
                "period_end": entry.period_end.isoformat() if entry and entry.period_end else None,
                "date": entry.date.isoformat() if entry else None,
                # 上次记的金额，**只作灰色占位提示**，不是预填的值
                "hint": prev_amounts.get(c.id),
                "hint_label": prev_labels.get(c.id),
            }
        )

    return {
        "period_id": period.id,
        "label": period.label,
        "status": period.status.value,
        "default_date": default_date_for(period).isoformat(),
        "rows": rows,
    }


def _last_amount_before(
    session: Session, category_ids: list[int], before: dt.date
) -> tuple[dict[int, int], dict[int, str]]:
    """每个分类在 before 之前最后一次记的金额，以及那笔落在哪一期。

    按分类回溯而不是只看上一期：水费两个月一收，上一期没有它；
    中间也可能夹着账目被删光的空账期。
    """
    if not category_ids:
        return {}, {}
    rows = session.exec(
        select(Entry)
        .where(
            Entry.category_id.in_(category_ids),
            Entry.date < before,
            Entry.deleted_at.is_(None),
            Entry.kind != EntryKind.settlement,
        )
        .order_by(Entry.date.desc(), Entry.id.desc())
    ).all()
    amounts: dict[int, int] = {}
    labels: dict[int, str] = {}
    period_labels: dict[int, str] = {}
    for e in rows:
        if e.category_id in amounts:
            continue                      # 已经拿到更晚的那笔了
        amounts[e.category_id] = e.amount_jpy
        if e.period_id is not None:
            if e.period_id not in period_labels:
                p = session.get(Period, e.period_id)
                period_labels[e.period_id] = p.label if p else ""
            labels[e.category_id] = period_labels[e.period_id]
    return amounts, labels
