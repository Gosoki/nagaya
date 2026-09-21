from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.models import Category, Entry, EntryShare, Member, Period
from app.schemas import EntryIn, EntryOut
from app.services import ledger

router = APIRouter(prefix="/api/entries", tags=["entries"])


def to_entry_out(session: Session, entry: Entry) -> EntryOut:
    shares = session.exec(select(EntryShare).where(EntryShare.entry_id == entry.id)).all()
    period = session.get(Period, entry.period_id) if entry.period_id else None
    return EntryOut(
        **entry.model_dump(),
        period_label=period.label if period else None,
        shares={str(s.member_id): s.amount_jpy for s in shares},
    )


def _category_rule(session: Session, category_id: int | None) -> dict | None:
    if category_id is None:
        return None
    category = session.get(Category, category_id)
    return category.default_rule_json if category else None


@router.get("", response_model=list[EntryOut])
def list_entries(
    period_id: int | None = None,
    since: dt.date | None = None,
    until: dt.date | None = None,
    include_deleted: bool = False,
    limit: int = Query(200, le=1000),
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    stmt = select(Entry).order_by(Entry.date.desc(), Entry.id.desc()).limit(limit)
    if not include_deleted:
        stmt = stmt.where(Entry.deleted_at.is_(None))
    if period_id is not None:
        stmt = stmt.where(Entry.period_id == period_id)
    if since is not None:
        stmt = stmt.where(Entry.date >= since)
    if until is not None:
        stmt = stmt.where(Entry.date <= until)
    return [to_entry_out(session, e) for e in session.exec(stmt)]


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
        period_start=body.period_start,
        period_end=body.period_end,
        bundle_id=body.bundle_id,
    )
    return to_entry_out(session, entry)


@router.patch("/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: int,
    body: EntryIn,
    version: int = Query(..., description="乐观锁：传你读到的那个 version"),
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账目不存在")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账目不存在")
    ledger.delete_entry(session, entry, actor_id=member.id)


@router.post("/{entry_id}/restore", response_model=EntryOut)
def restore_entry(
    entry_id: int,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账目不存在")
    ledger.restore_entry(session, entry, actor_id=member.id)
    return to_entry_out(session, entry)
