from __future__ import annotations

import datetime as dt
from typing import Sequence

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.errors import not_found
from app.models import Category, Entry, EntryShare, Member, Statement
from app.schemas import EntryIn, EntryOut, EntryPatch
from app.services import ledger

router = APIRouter(prefix="/api/entries", tags=["entries"])


def to_entry_out(session: Session, entry: Entry) -> EntryOut:
    return _to_out(entry, _shares_by_entry(session, [entry.id]), _labels(session, [entry.statement_id]))


def _shares_by_entry(session: Session, entry_ids: Sequence[int]) -> dict[int, dict[str, int]]:
    """一次把这些账目的分摊全捞出来。

    原来是一笔一查：列表接口 500 笔就是 1000 次查询（分摊一次、所属账单一次），
    而这个接口每次开 App、每次记完账都要调。
    """
    out: dict[int, dict[str, int]] = {}
    if not entry_ids:
        return out
    rows = session.exec(select(EntryShare).where(EntryShare.entry_id.in_(entry_ids)))  # type: ignore[attr-defined]
    for row in rows:
        out.setdefault(row.entry_id, {})[str(row.member_id)] = row.amount_jpy
    return out


def _labels(session: Session, statement_ids: Sequence[int | None]) -> dict[int, str]:
    ids = {i for i in statement_ids if i is not None}
    if not ids:
        return {}
    rows = session.exec(select(Statement).where(Statement.id.in_(ids)))  # type: ignore[attr-defined]
    return {s.id: s.label for s in rows}


def _to_out(entry: Entry, shares: dict[int, dict[str, int]], labels: dict[int, str]) -> EntryOut:
    return EntryOut(
        **entry.model_dump(),
        statement_label=labels.get(entry.statement_id) if entry.statement_id else None,
        shares=shares.get(entry.id, {}),
    )


def _category_rule(session: Session, category_id: int | None) -> dict | None:
    if category_id is None:
        return None
    category = session.get(Category, category_id)
    return category.default_rule_json if category else None


@router.get("", response_model=list[EntryOut])
def list_entries(
    statement_id: int | None = None,
    unbilled_only: bool = False,
    since: dt.date | None = None,
    until: dt.date | None = None,
    include_deleted: bool = False,
    # ge=1 不是洁癖：limit=-1 会变成 SQL 的 LIMIT -1 ＝ 不限，
    # 一次把整个账本吐出来，还让「只算了最近 500 笔」那句截断提示失真
    limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    stmt = select(Entry).order_by(Entry.date.desc(), Entry.id.desc()).limit(limit)
    if not include_deleted:
        stmt = stmt.where(Entry.deleted_at.is_(None))
    if statement_id is not None:
        stmt = stmt.where(Entry.statement_id == statement_id)
    if unbilled_only:
        stmt = stmt.where(Entry.statement_id.is_(None))
    if since is not None:
        stmt = stmt.where(Entry.date >= since)
    if until is not None:
        stmt = stmt.where(Entry.date <= until)
    rows = list(session.exec(stmt))
    shares = _shares_by_entry(session, [e.id for e in rows])
    labels = _labels(session, [e.statement_id for e in rows])
    return [_to_out(e, shares, labels) for e in rows]


@router.get("/{entry_id}", response_model=EntryOut)
def get_entry(
    entry_id: int,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    """单独取一笔 —— 编辑页按 id 直接开，刷新和深链都能用。"""
    entry = session.get(Entry, entry_id)
    if entry is None or entry.deleted_at is not None:
        raise not_found("entry")
    return to_entry_out(session, entry)


@router.post("", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: EntryIn,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = ledger.create_entry(
        session,
        actor_id=member.id,
        kind=body.kind,
        on=body.date,
        amount=body.amount_jpy,
        payer_id=body.payer_id,
        rule=body.rule,
        category_rule=_category_rule(session, body.category_id),
        member_ids=body.member_ids,
        to_member_id=body.to_member_id,
        category_id=body.category_id,
        title=body.title,
        note=body.note,
        bundle_id=body.bundle_id,
    )
    return to_entry_out(session, entry)


@router.patch("/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: int,
    body: EntryPatch,
    version: int = Query(..., description="乐观锁：传你读到的那个 version"),
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise not_found("entry")
    fields = body.model_dump(exclude_unset=True, exclude={"rule", "member_ids"})
    entry = ledger.update_entry(
        session,
        entry,
        actor_id=member.id,
        version=version,
        fields=fields,
        rule=body.rule,
        category_rule=_category_rule(session, body.category_id),
        member_ids=body.member_ids,
    )
    return to_entry_out(session, entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: int,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise not_found("entry")
    ledger.delete_entry(session, entry, actor_id=member.id)


@router.post("/{entry_id}/restore", response_model=EntryOut)
def restore_entry(
    entry_id: int,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise not_found("entry")
    ledger.restore_entry(session, entry, actor_id=member.id)
    return to_entry_out(session, entry)
