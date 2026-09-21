from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import current_member, hash_password
from app.db import get_session
from app.models import Member
from app.routers.auth import to_member_out
from app.schemas import MemberIn, MemberOut

router = APIRouter(prefix="/api/members", tags=["members"])


@router.get("", response_model=list[MemberOut])
def list_members(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    rows = session.exec(select(Member).order_by(Member.display_order, Member.id)).all()
    return [to_member_out(m) for m in rows]


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def create_member(
    body: MemberIn,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    if not body.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "登录名不能为空")
    if session.exec(select(Member).where(Member.name == body.name)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"登录名 {body.name} 已存在")

    data = body.model_dump(exclude_none=True, exclude={"password"})
    data.setdefault("display_name", body.name)
    member = Member(**data)
    if body.password:
        member.password_hash = hash_password(body.password)
    session.add(member)
    session.commit()
    session.refresh(member)
    return to_member_out(member)


@router.patch("/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    body: MemberIn,
    session: Session = Depends(get_session),
    me: Member = Depends(current_member),
):
    member = session.get(Member, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成员不存在")

    # **密码只能自己改。** 这屋里三个人是互相信任的，但「信任」不该等于
    # 「谁都能把别人锁在门外」—— 改掉别人的密码是一个没法自己恢复的动作
    if body.password is not None and member.id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能改自己的密码")

    # exclude_unset 而不是 exclude_none：PATCH 的语义是「我发了什么就改什么」。
    # 用 exclude_none 的话 left_on 一旦填错就再也清不掉 —— null 会被当成「没发」，
    # 于是那个人永远是「已退出」，回不来
    fields = body.model_dump(exclude_unset=True, exclude={"password"})
    if "name" in fields:
        if not fields["name"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "登录名不能为空")
        clash = session.exec(select(Member).where(Member.name == fields["name"])).first()
        if clash is not None and clash.id != member_id:
            # 这一条原来会撞穿到数据库的唯一约束，返回 500；POST 那边早就是 409 了
            raise HTTPException(status.HTTP_409_CONFLICT, f"登录名 {fields['name']} 已存在")
    for key, value in fields.items():
        setattr(member, key, value)
    if body.password:
        member.password_hash = hash_password(body.password)
    session.add(member)
    session.commit()
    session.refresh(member)
    return to_member_out(member)
