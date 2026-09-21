from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import current_member
from app.core.rules import RuleError, expand
from app.core.split import SplitError, split
from app.db import get_session
from app.models import Member
from app.schemas import SettingIn, SettingOut
from app.services import settings as settings_svc
from app.settings_spec import SETTINGS_SPEC

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=list[SettingOut])
def list_settings(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    """连同 type / 取值范围 / 中日文说明一起给出去，面板照着渲染就行。"""
    out = []
    for key, spec in SETTINGS_SPEC.items():
        out.append(
            SettingOut(
                key=key,
                value=settings_svc.get(session, key),
                type=spec["type"],
                note_zh=spec["note_zh"],
                note_ja=spec["note_ja"],
                options=spec.get("options"),
                min=spec.get("min"),
                max=spec.get("max"),
            )
        )
    return out


@router.put("/{key}", response_model=SettingOut)
def update_setting(
    key: str,
    body: SettingIn,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
):
    if key not in SETTINGS_SPEC:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"没有这个配置项：{key}")
    spec = SETTINGS_SPEC[key]
    value = body.value

    if spec["type"] in {"int", "int_or_null"}:
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 要填整数")
            lo, hi = spec.get("min"), spec.get("max")
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 要在 {lo}〜{hi} 之间")
        elif spec["type"] == "int":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 不能留空")
    elif spec["type"] == "enum" and value not in spec["options"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 只能是 {spec['options']} 之一")
    elif spec["type"] == "bool" and not isinstance(value, bool):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 要填 true/false")
    elif spec["type"] == "string_list" and not (
        isinstance(value, list) and all(isinstance(v, str) for v in value)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 要填字符串列表")
    elif spec["type"] == "json":
        # **当场试着用一下**。这一项是每笔账的兜底分摊规则，写坏了不会在这里报错，
        # 而是等到下一次「记一笔」时才 500 —— 那时人正在记账，也看不出跟设置有关
        if not isinstance(value, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 要填一个对象")
        try:
            ids = [m.id for m in session.exec(select(Member).order_by(Member.display_order))]
            split(expand(value, ids), 1000, order=[str(i) for i in ids], payer=str(ids[0]) if ids else None)
        except (RuleError, SplitError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key} 这条规则用不了：{e}") from e

    settings_svc.set_(session, key, value)
    return SettingOut(
        key=key, value=value, type=spec["type"],
        note_zh=spec["note_zh"], note_ja=spec["note_ja"],
        options=spec.get("options"), min=spec.get("min"), max=spec.get("max"),
    )
