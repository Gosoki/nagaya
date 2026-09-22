"""备忘条目。

固定费那几项的备忘写在 Category.note 上（它们本来就是一份现成的清单），
这里只管清单之外的东西：备用钥匙放哪、垃圾袋买哪种、房东电话。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.errors import AppError, not_found
from app.models import Member, Memo, now_utc
from app.schemas import MemoIn, MemoOut

router = APIRouter(prefix="/api/memos", tags=["memos"])

#: 和账目的备注一个道理：不设上限的话 50 万字的 body 也照收
MAX_TITLE = 200
MAX_BODY = 10_000


def _check_len(title: str | None, body: str | None) -> None:
    if title is not None and len(title) > MAX_TITLE:
        raise AppError("text_too_long", "memo title too long", field="title", limit=MAX_TITLE)
    if body is not None and len(body) > MAX_BODY:
        raise AppError("text_too_long", "memo body too long", field="body", limit=MAX_BODY)


@router.get("", response_model=list[MemoOut])
def list_memos(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    return list(session.exec(select(Memo).order_by(Memo.display_order, Memo.id)))


@router.post("", response_model=MemoOut, status_code=status.HTTP_201_CREATED)
def create_memo(
    body: MemoIn,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    if not (body.title or "").strip():
        raise AppError("name_required", "memo needs a title")
    _check_len(body.title, body.body)
    # 新的排在最后：列表顺序是人自己排出来的，新条目不该插队
    last = session.exec(select(Memo).order_by(Memo.display_order.desc())).first()  # type: ignore[attr-defined]
    row = Memo(
        title=body.title.strip(),
        body=body.body or "",
        display_order=body.display_order
        if body.display_order is not None
        else ((last.display_order + 1) if last else 0),
        created_by=member.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/{memo_id}", response_model=MemoOut)
def update_memo(
    memo_id: int,
    body: MemoIn,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    row = session.get(Memo, memo_id)
    if row is None:
        raise not_found("memo")
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields and not (fields["title"] or "").strip():
        raise AppError("name_required", "memo needs a title")
    _check_len(fields.get("title"), fields.get("body"))
    for key, value in fields.items():
        setattr(row, key, value.strip() if key == "title" else value)
    row.updated_at = now_utc()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.delete("/{memo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memo(
    memo_id: int,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    row = session.get(Memo, memo_id)
    if row is None:
        raise not_found("memo")
    # 真删。备忘不是账 —— 账要能追溯所以软删，一条「垃圾袋买大号的」不需要回收站
    session.delete(row)
    session.commit()
