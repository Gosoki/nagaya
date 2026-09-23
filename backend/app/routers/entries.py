from __future__ import annotations

import threading
from typing import Sequence

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.errors import not_found
from app.models import Category, Entry, EntryShare, Member, RequestKey, Statement
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
    # 只取三列：500 笔 × 三个人，逐行造 ORM 对象比查询本身还贵
    rows = session.exec(
        select(EntryShare.entry_id, EntryShare.member_id, EntryShare.amount_jpy).where(
            EntryShare.entry_id.in_(entry_ids)  # type: ignore[attr-defined]
        )
    )
    for eid, mid, amount in rows:
        out.setdefault(eid, {})[str(mid)] = amount
    return out


def _labels(session: Session, statement_ids: Sequence[int | None]) -> dict[int, Statement]:
    ids = {i for i in statement_ids if i is not None}
    if not ids:
        return {}
    rows = session.exec(select(Statement).where(Statement.id.in_(ids)))  # type: ignore[attr-defined]
    return {s.id: s for s in rows}


def _to_out(entry: Entry, shares: dict[int, dict[str, int]], labels: dict[int, Statement]) -> EntryOut:
    st = labels.get(entry.statement_id) if entry.statement_id else None
    return EntryOut(
        **entry.model_dump(),
        statement_label=st.label if st else None,
        statement_cut_at=st.cut_at if st else None,
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
    # ge=1 不是洁癖：limit=-1 会变成 SQL 的 LIMIT -1 ＝ 不限，
    # 一次把整个账本吐出来，还让「只算了最近 500 笔」那句截断提示失真
    limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    stmt = (
        select(Entry).where(Entry.deleted_at.is_(None)).order_by(Entry.date.desc(), Entry.id.desc()).limit(limit)
    )
    if statement_id is not None:
        stmt = stmt.where(Entry.statement_id == statement_id)
    if unbilled_only:
        stmt = stmt.where(Entry.statement_id.is_(None))
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


#: 「查幂等键 → 记账 → 写幂等键」必须是一步：两条带同一个键的请求并发进来
#: （补交时网又抖了一下、前端重试）不能各记一笔。服务是单进程，进程锁就够
_create_lock = threading.Lock()


@router.post("", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: EntryIn,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    if body.client_key is None:
        return to_entry_out(session, _create(session, body, member))
    with _create_lock:
        seen = session.get(RequestKey, body.client_key)
        if seen is not None:
            # 这笔早就记上了（多半是上次响应丢在路上）：原样还给它，不再记一遍
            old = session.get(Entry, seen.entry_id)
            if old is not None:
                return to_entry_out(session, old)
        return to_entry_out(session, _create(session, body, member))


def _create(session: Session, body: EntryIn, member: Member) -> Entry:
    return ledger.create_entry(
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
        client_key=body.client_key,
    )


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
    # 可选：带上就按乐观锁核一遍（别人刚改过/刚被出账带走就 409）。
    # 不带是给还装在手机上的旧版页面留的路
    version: int | None = Query(None),
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise not_found("entry")
    ledger.delete_entry(session, entry, actor_id=member.id, version=version)


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
