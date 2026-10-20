from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session, select

from app.auth import current_member
from app.core.rules import RuleError
from app.core.split import SplitError, try_default_rule
from app.db import get_session
from app.errors import AppError, not_found, reject_nulls
from app.models import Category, Member, today_jst
from app.schemas import CategoryIn, CategoryOut
from app.services import audit
from app.services.ledger import active_members

router = APIRouter(prefix="/api/categories", tags=["categories"])

#: 文字字段的上限（和账目、备忘一样只防滥用，正常用碰不到）。不设的话一个分类名能塞进几兆
MAX_TEXT = {"name": 64, "icon": 64, "color": 64, "note": 2_000}


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
    for field, limit in MAX_TEXT.items():
        value = getattr(body, field)
        if isinstance(value, str) and len(value) > limit:
            raise AppError("text_too_long", f"category {field} too long", field=field, limit=limit)
    if body.default_payer_id is not None and session.get(Member, body.default_payer_id) is None:
        raise AppError("not_found", "member not found", what="member", member_id=body.default_payer_id)
    if body.default_rule_json is not None:
        try:
            try_default_rule(body.default_rule_json, [m.id for m in active_members(session, today_jst())])
        except (RuleError, SplitError) as e:
            raise AppError("bad_rule", f"category rule unusable: {e}", why=e.code) from e
    if body.name is not None:
        _refuse_clash(session, body.name, me)


def _refuse_clash(session: Session, name: str, me: int | None) -> None:
    """在用的分类里已经有这个名字了就拒收（归档的不算）"""
    clash = session.exec(
        select(Category).where(
            Category.name == name,
            Category.archived == False,  # noqa: E712
        )
    ).first()
    if clash is not None and clash.id != me:
        raise AppError("name_taken", f"category {name} exists", status=409, name=name)


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
    me: Member = Depends(current_member),
):
    # strip 之后再判空：三个空格原来是收的，库里就多一个看不见名字的分类
    body.name = (body.name or "").strip() or None
    if not body.name:
        raise AppError("name_required", "category needs a name")
    _check(session, body)
    row = Category(**body.model_dump(exclude_none=True))
    session.add(row)
    session.flush()
    audit.config(session, me.id, "create", "category", row.id, None, row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryIn,
    session: Session = Depends(get_session),
    me: Member = Depends(current_member),
):
    row = session.get(Category, category_id)
    if row is None:
        raise not_found("category")
    if body.name is not None:
        body.name = body.name.strip()
        if not body.name:
            raise AppError("name_required", "category needs a name")
    _check(session, body, me=category_id)
    # 取消归档（固定费面板上的「撤销」只发 archived:false）也得查重：归档期间
    # 可能又建了一个同名的，不查就复活出两个一模一样的分类，改哪个删哪个全靠猜
    if body.archived is False and row.archived and body.name is None:
        _refuse_clash(session, row.name, category_id)
    # default_rule_json / default_payer_id 要能被显式清空（None 在这里是「清掉」的意思），
    # 其余几个是 NOT NULL —— 传 null 进来得当场挡掉，不然要等 commit 才炸成 500
    data = body.model_dump(exclude_unset=True)
    reject_nulls(data, ("name", "icon", "color", "monthly", "display_order",
                        "archived", "same_as_last", "note"))
    before = row.model_copy()
    for key, value in data.items():
        setattr(row, key, value)
    session.add(row)
    audit.config(session, me.id, "update", "category", row.id, before, row)
    session.commit()
    session.refresh(row)
    return row
