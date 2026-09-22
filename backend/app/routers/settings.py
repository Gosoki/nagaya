from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth import current_member
from app.core.rules import RuleError, expand
from app.core.split import SplitError, split
from app.db import get_session
from app.errors import AppError, not_found
from app.models import Category, Member
from app.schemas import SettingIn, SettingOut
from app.services import settings as settings_svc
from app.settings_spec import SETTINGS_SPEC

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _bad(key: str, want: str) -> AppError:
    """这一项的值不对。**一个码就够**：用户正看着那一格，界面上说
    「「余数归谁」这个设置的值不对」他就知道是哪儿了 —— 为十来种类型各造一个码，
    翻出来的十几句话说的是同一件事，还容易翻歪。具体想要什么放 detail 里给排查用。"""
    return AppError("setting_invalid", f"{key} wants {want}", key=key, want=want)


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
        raise not_found("setting")
    spec = SETTINGS_SPEC[key]
    value = body.value

    # 引用类的两项要查存在性。原来 member_id_or_null **一个分支都没匹配上**，
    # 直接穿过整条 if/elif 落库：实测 "不是数字" / {"a":1} / [1,2,3] / 3.14 / 99999 全收。
    # 存进去之后固定费面板拿它当兜底垫付人，记账当场 400 unknown_member，
    # 而报错指向的是账目、不是这条设置 —— 人被卡在「记不了账」且找不到原因。
    # 同一个文件里 json 类型的设置是「当场试着用一下」的，这一层照做
    if spec["type"] == "member_id_or_null" or key.endswith("_category_id"):
        model = Member if spec["type"] == "member_id_or_null" else Category
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise _bad(key, "id")
            if session.get(model, value) is None:
                raise AppError("not_found", f"{key} points nowhere", what="setting_ref", key=key)
    elif spec["type"] == "str" and not isinstance(value, str):
        raise _bad(key, "str")
    elif spec["type"] in {"int", "int_or_null"}:
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise _bad(key, "int")
            lo, hi = spec.get("min"), spec.get("max")
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                # 越界单独一个码：这是面板上**唯一碰得到**的一种（数字框），
                # 而「要在 0〜90 之间」正是这一条里唯一有用的信息 ——
                # 归进 setting_invalid 的话说出来的只剩「值不对」
                raise AppError(
                    "setting_out_of_range", f"{key} must be {lo}..{hi}",
                    key=key, min=lo, max=hi,
                )
        elif spec["type"] == "int":
            raise _bad(key, "required")
    elif spec["type"] == "enum" and value not in spec["options"]:
        raise _bad(key, str(spec["options"]))
    elif spec["type"] == "bool" and not isinstance(value, bool):
        raise _bad(key, "true/false")
    elif spec["type"] == "string_list" and not (
        isinstance(value, list) and all(isinstance(v, str) for v in value)
    ):
        raise _bad(key, "list")
    elif spec["type"] == "json":
        # **当场试着用一下**。这一项是每笔账的兜底分摊规则，写坏了不会在这里报错，
        # 而是等到下一次「记一笔」时才 500 —— 那时人正在记账，也看不出跟设置有关
        if not isinstance(value, dict):
            raise _bad(key, "object")
        try:
            ids = [m.id for m in session.exec(select(Member).order_by(Member.display_order))]
            split(expand(value, ids), 1000, order=[str(i) for i in ids], payer=str(ids[0]) if ids else None)
        except (RuleError, SplitError) as e:
            raise AppError("bad_rule", f"{key} rule unusable: {e}", key=key, why=str(e)) from e

    settings_svc.set_(session, key, value)
    return SettingOut(
        key=key, value=value, type=spec["type"],
        note_zh=spec["note_zh"], note_ja=spec["note_ja"],
        options=spec.get("options"), min=spec.get("min"), max=spec.get("max"),
    )
