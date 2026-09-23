"""配置读写。缺省值来自 settings_spec.SETTINGS_SPEC，代码里只留兜底。"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import Setting, now_utc
from app.settings_spec import SETTINGS_SPEC


def seed_settings(session: Session) -> None:
    """把声明里有、表里还没有的项按默认值补进去。已存在的值不动。
    说明文字不进库：接口直接从 SETTINGS_SPEC 拿，改文案不用碰数据"""
    for key, spec in SETTINGS_SPEC.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value_json=spec["default"]))
    session.commit()


def get(session: Session, key: str) -> Any:
    if key not in SETTINGS_SPEC:
        raise KeyError(f"未声明的配置项：{key}")
    row = session.get(Setting, key)
    return SETTINGS_SPEC[key]["default"] if row is None else row.value_json


def set_(session: Session, key: str, value: Any) -> None:
    if key not in SETTINGS_SPEC:
        raise KeyError(f"未声明的配置项：{key}")
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key)
    row.value_json = value
    row.updated_at = now_utc()
    session.add(row)
    session.commit()


def all_settings(session: Session) -> list[Setting]:
    return list(session.exec(select(Setting)))
