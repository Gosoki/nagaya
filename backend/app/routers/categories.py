from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.models import Category, Member
from app.schemas import CategoryIn, CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(
    include_archived: bool = False,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    stmt = select(Category).order_by(Category.display_order, Category.id)
    if not include_archived:
        stmt = stmt.where(Category.archived == False)  # noqa: E712
    return list(session.exec(stmt))


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryIn,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    if not body.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "分类名不能为空")
    row = Category(**body.model_dump(exclude_none=True))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryIn,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    row = session.get(Category, category_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分类不存在")
    # default_rule_json 要能被显式清空，所以单独处理（None 在这里是「清掉」的意思）
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
