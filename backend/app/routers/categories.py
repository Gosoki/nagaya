from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session, select

from app.auth import current_member
from app.core.rules import RuleError, expand
from app.core.split import SplitError, split
from app.db import get_session
from app.errors import AppError, not_found, reject_nulls
from app.models import Category, Member
from app.schemas import CategoryIn, CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _check(session: Session, body: CategoryIn, *, me: int | None = None) -> None:
    """建/改一个分类之前该验的三件事。

    三件都对应一次真实的坏结局：
      * **垫付人乱指** —— 外键直接撞穿，返回 500；
      * **分摊规则写坏** —— 这里一声不吭，等到有人选这个分类记账时才炸
        `unknown_mode`，而那句提示完全看不出跟分类设置有关。
        设置面板对 json 类型的做法就是「当场试着用一下」，这一层照抄；
      * **同名** —— 分类名是界面上唯一的标识，重名之后两行长得一模一样，
        改哪个、删哪个全靠猜。
    """
    if body.default_payer_id is not None and session.get(Member, body.default_payer_id) is None:
        raise AppError("not_found", "member not found", what="member", member_id=body.default_payer_id)
    if body.default_rule_json is not None:
        ids = [m.id for m in session.exec(select(Member).order_by(Member.display_order))]
        try:
            split(
                expand(body.default_rule_json, ids),
                1000,
                order=[str(i) for i in ids],
                payer=str(ids[0]) if ids else None,
            )
        except (RuleError, SplitError) as e:
            raise AppError("bad_rule", f"category rule unusable: {e}", why=str(e)) from e
    if body.name is not None:
        clash = session.exec(
            select(Category).where(
                Category.name == body.name,
                Category.archived == False,  # noqa: E712
            )
        ).first()
        if clash is not None and clash.id != me:
            raise AppError("name_taken", f"category {body.name} exists", status=409, name=body.name)


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
    # strip 之后再判空：三个空格原来是收的，库里就多一个看不见名字的分类
    body.name = (body.name or "").strip() or None
    if not body.name:
        raise AppError("name_required", "category needs a name")
    _check(session, body)
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
        raise not_found("category")
    if body.name is not None:
        body.name = body.name.strip()
        if not body.name:
            raise AppError("name_required", "category needs a name")
    _check(session, body, me=category_id)
    # default_rule_json / default_payer_id 要能被显式清空（None 在这里是「清掉」的意思），
    # 其余几个是 NOT NULL —— 传 null 进来得当场挡掉，不然要等 commit 才炸成 500
    data = body.model_dump(exclude_unset=True)
    reject_nulls(data, ("name", "icon", "color", "monthly", "display_order",
                        "archived", "same_as_last", "note"))
    for key, value in data.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
