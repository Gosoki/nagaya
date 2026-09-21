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
from typing import Any

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
    today_jst,
)
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
    rows = session.exec(select(EntryShare).where(EntryShare.entry_id.in_(entry_ids))).all()
    out: dict[int, dict[int, int]] = {}
    for r in rows:
        out.setdefault(r.entry_id, {})[r.member_id] = r.amount_jpy
    return out


def _net(session: Session, entries: list[Entry]) -> dict[int, int]:
    """这批账目让每个人的余额net变化多少（＝付出 − 应担）。"""
    shares = _shares_of(session, [e.id for e in entries])
    net: dict[int, int] = {}
    for e in entries:
        net[e.payer_id] = net.get(e.payer_id, 0) + e.amount_jpy
        for m, sh in shares.get(e.id, {}).items():
            net[m] = net.get(m, 0) - sh
    return net


def _entries_before(session: Session, statement: Statement | None) -> list[Entry]:
    """在这张账单之前就已经出过账的全部账目 —— 用来算「上期结转」。"""
    stmt = select(Entry).where(Entry.deleted_at.is_(None), Entry.statement_id.is_not(None))
    if statement is not None:
        earlier = [
            s.id
            for s in session.exec(select(Statement).where(Statement.cut_at < statement.cut_at))
        ]
        if not earlier:
            return []
        stmt = stmt.where(Entry.statement_id.in_(earlier))
    return list(session.exec(stmt))


# ------------------------------------------------------------------ 账单


def build_bill(session: Session, statement: Statement | None = None) -> dict[str, Any]:
    """statement 传 None ＝ 当前这张还没出的草稿账单。"""
    entries = unbilled(session) if statement is None else entries_of(session, statement.id)
    shares = _shares_of(session, [e.id for e in entries])
    members = list(session.exec(select(Member).order_by(Member.display_order, Member.id)))
    opening = _net(session, _entries_before(session, statement))

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
    transfers: list[Transfer] = (
        plan_simplified(closing)
        if simplify
        else plan_pairwise(_pair_debts(session, _entries_before(session, statement) + entries))
    )

    dates = [e.date for e in entries]
    return {
        "statement_id": statement.id if statement else None,
        "label": statement.label if statement else None,
        "is_draft": statement is None,
        "cut_at": statement.cut_at.isoformat() if statement else None,
        "covers_from": min(dates).isoformat() if dates else None,
        "covers_to": max(dates).isoformat() if dates else None,
        "total_expense": total_expense,
        "total_income": total_income,
        "entry_count": len(entries),
        "members": rows,
        "transfers": [t._asdict() for t in transfers],
        "simplified": simplify,
        "covers": [
            {
                "entry_id": e.id,
                "title": e.title,
                "category_id": e.category_id,
                "period_start": e.period_start.isoformat() if e.period_start else None,
                "period_end": e.period_end.isoformat() if e.period_end else None,
            }
            for e in entries
            if e.period_start or e.period_end
        ],
        # 出账之后又被改过的话要说出来，否则下一张的「上期结转」没人解释得清
        "edited_after_cut": _edited_after_cut(session, statement),
    }


def _pair_debts(session: Session, entries: list[Entry]) -> dict[tuple[int, int], int]:
    """逐对债权，用于「按原始债权结算」：谁垫的钱就还给谁。"""
    shares = _shares_of(session, [e.id for e in entries])
    debts: dict[tuple[int, int], int] = {}
    for e in entries:
        if e.kind == EntryKind.settlement:
            if e.to_member_id is not None:
                key = (e.to_member_id, e.payer_id)
                debts[key] = debts.get(key, 0) + e.amount_jpy
            continue
        for m, sh in shares.get(e.id, {}).items():
            if m == e.payer_id or sh == 0:
                continue
            key = (m, e.payer_id)
            debts[key] = debts.get(key, 0) + sh
    return debts


def _edited_after_cut(session: Session, statement: Statement | None) -> dict[str, Any] | None:
    """这张账单出完之后有没有被动过。

    不锁定历史（余额全局累计，改了也不会算错钱），但**必须让改动可见** ——
    否则下一张账单上冒出来的「上期结转」没人解释得清。
    """
    if statement is None:
        return None
    logs = session.exec(
        select(AuditLog).where(
            AuditLog.target_table == "entry",
            AuditLog.at > statement.cut_at,
            AuditLog.action.in_(["update", "delete", "restore"]),
        )
    ).all()
    touched = {
        l.target_id
        for l in logs
        if l.target_id is not None
        and (session.get(Entry, l.target_id) is not None)
        and session.get(Entry, l.target_id).statement_id == statement.id
    }
    if not touched:
        return None
    frozen = (statement.snapshot_json or {}).get("total_expense")
    live = build_total_expense(session, statement)
    return {"count": len(touched), "frozen_total": frozen, "live_total": live}


def build_total_expense(session: Session, statement: Statement) -> int:
    return sum(
        e.amount_jpy for e in entries_of(session, statement.id) if e.kind == EntryKind.expense
    )


# ------------------------------------------------------------------ 出账


def cut_statement(session: Session, *, actor_id: int | None, label: str | None = None) -> Statement:
    """出账单：把这一刻之前所有没出账的账目归到一张单子上，并冻结快照。"""
    entries = unbilled(session)
    if not entries:
        raise BillError("nothing_to_cut", "现在没有待出账的账目")

    dates = [e.date for e in entries]
    today = today_jst()
    statement = Statement(
        label=label or f"{today.month}/{today.day} 出账",
        cut_at=now_utc(),
        covers_from=min(dates),
        covers_to=max(dates),
        cut_by=actor_id,
    )
    session.add(statement)
    session.flush()

    for e in entries:
        e.statement_id = statement.id
        session.add(e)
    session.flush()

    statement.snapshot_json = build_bill(session, statement)
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


# ------------------------------------------------- 当前草稿账单上的「固定费」


def monthly_rows(session: Session) -> dict[str, Any]:
    """每月一次的固定项在**当前草稿账单**里的状态。

    没录的给「上次这项记了多少」当灰色参考 —— 注意它只是 placeholder，不是值。
    账本里预填的数字很危险：长得跟亲手填的一模一样，某个月忘了改就带着上月的
    电费把账单发出去了，谁都看不出来。
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
        for e in unbilled(session)
        if e.kind != EntryKind.settlement and e.category_id is not None
    }
    hints, hint_labels = _last_billed_amount(session, [c.id for c in categories])

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
                "hint": hints.get(c.id),
                "hint_label": hint_labels.get(c.id),
            }
        )

    return {
        "default_date": today_jst().isoformat(),
        "rows": rows,
    }


def _last_billed_amount(
    session: Session, category_ids: list[int]
) -> tuple[dict[int, int], dict[int, str]]:
    """每个分类**上一次出过账的**金额，以及那笔在哪张单子上。

    按分类回溯而不是只看上一张单子：水费两个月一收，上一张本来就没有它。
    """
    if not category_ids:
        return {}, {}
    rows = session.exec(
        select(Entry)
        .where(
            Entry.category_id.in_(category_ids),
            Entry.deleted_at.is_(None),
            Entry.statement_id.is_not(None),
            Entry.kind != EntryKind.settlement,
        )
        .order_by(Entry.date.desc(), Entry.id.desc())
    ).all()
    amounts: dict[int, int] = {}
    labels: dict[int, str] = {}
    cache: dict[int, str] = {}
    for e in rows:
        if e.category_id in amounts:
            continue
        amounts[e.category_id] = e.amount_jpy
        if e.statement_id not in cache:
            st = session.get(Statement, e.statement_id)
            cache[e.statement_id] = st.label if st else ""
        labels[e.category_id] = cache[e.statement_id]
    return amounts, labels
