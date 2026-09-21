from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.auth import authenticate, current_member, make_token
from app.db import get_session
from app.models import Member
from app.schemas import LoginIn, LoginOut, MemberOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_member_out(m: Member) -> MemberOut:
    data = m.model_dump()
    blob = data.pop("avatar", None)
    return MemberOut(
        **data,
        is_active=m.is_active(),
        avatar=f"data:image/webp;base64,{base64.b64encode(blob).decode()}" if blob else None,
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, session: Session = Depends(get_session)) -> LoginOut:
    member = authenticate(session, body.name, body.password)
    if member is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码不对")
    return LoginOut(token=make_token(member.id), member=to_member_out(member))


@router.get("/me", response_model=MemberOut)
def me(member: Member = Depends(current_member)) -> MemberOut:
    return to_member_out(member)
