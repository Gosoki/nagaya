"""备忘条目。

固定费那几项的备忘写在 Category.note 上（它们本来就是一份现成的清单），
这里只管清单之外的东西：备用钥匙放哪、垃圾袋买哪种、房东电话。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.models import Member, Memo, now_utc
from app.schemas import MemoIn, MemoOut

router = APIRouter(prefix="/api/memos", tags=["memos"])


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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "备忘要有个名字")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "备忘不存在")
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields and not (fields["title"] or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "备忘要有个名字")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "备忘不存在")
    # 真删。备忘不是账 —— 账要能追溯所以软删，一条「垃圾袋买大号的」不需要回收站
    session.delete(row)
    session.commit()
