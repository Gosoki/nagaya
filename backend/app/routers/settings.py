from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.auth import current_member
from app.core.rules import RuleError, expand
from app.core.split import SplitError, split
from app.db import get_session
from app.errors import AppError, not_found
from app.models import Category, Member, today_jst
from app.schemas import SettingIn, SettingOut
from app.services import ledger as ledger_svc
from app.services import settings as settings_svc
from app.services.backup import resolve_backup_path as backup_dir_for
from app.settings_spec import SETTINGS_SPEC

router = APIRouter(prefix="/api/settings", tags=["settings"])

#: 前端产物所在的整个前端目录（main.py 里 DIST 的上两级）。备份不许落在这下面
WEB_ROOT = (Path(__file__).resolve().parents[3] / "frontend").resolve()


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
                hidden=bool(spec.get("hidden")),
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
    me: Member = Depends(current_member),
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
    elif key == "backup_path":
        # 备份是整本账的明文（含密码哈希）。**不许指进前端产物目录** ——
        # 那个目录整个对外发，未登录就能下载。NUL 字符会让后面建目录时直接 500
        if "\x00" in value:
            raise _bad(key, "path")
        try:
            target = backup_dir_for(value)
        except ValueError:
            raise _bad(key, "path") from None
        if target == WEB_ROOT or target.is_relative_to(WEB_ROOT):
            raise _bad(key, "outside web root")
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
        # 全局兜底规则不可能是定额：定额要和每一笔的总额对得上，而它要套在任意金额上
        if value.get("mode") == "exact":
            raise AppError("bad_rule", f"{key} cannot be exact", key=key, why="exact")
        try:
            # 拿**今天在籍的人**、几个不同的金额各试一次：只拿 1000 试一次的话，
            # 整除的那几种情况把坏规则放了过去（比如余数规则写坏了，1000/2 人不报）
            ids = [m.id for m in ledger_svc.active_members(session, today_jst())]
            order = [str(i) for i in ids]
            for amount in (1, 999, 1_001, 100_003):
                split(expand(value, ids), amount, order=order, payer=order[0] if order else None)
        except (RuleError, SplitError) as e:
            raise AppError("bad_rule", f"{key} rule unusable: {e}", key=key, why=str(e)) from e

    # 留痕：余数归谁、兜底规则、默认垫付人这些一改，之后每一笔都换一种分法。
    # set_ 自己 commit，审计那一行跟着它一起进库
    ledger_svc.audit_config(
        session, me.id, "update", "setting", None,
        {"key": key, "value": settings_svc.get(session, key)}, {"key": key, "value": value},
    )
    settings_svc.set_(session, key, value)
    return SettingOut(
        key=key, value=value, type=spec["type"], hidden=bool(spec.get("hidden")),
        note_zh=spec["note_zh"], note_ja=spec["note_ja"],
        options=spec.get("options"), min=spec.get("min"), max=spec.get("max"),
    )
