"""API 的出入参。后端只返数据和枚举 key，**不返界面文案**（文案全在前端 vue-i18n）。"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from sqlmodel import SQLModel

from app.models import EntryKind, Lang, PeriodStatus


class LoginIn(SQLModel):
    name: str
    password: str


class MemberOut(SQLModel):
    id: int
    name: str
    display_name: str
    color: str
    display_order: int
    joined_on: dt.date
    left_on: Optional[dt.date]
    lang: Lang
    is_active: bool


class LoginOut(SQLModel):
    token: str
    member: MemberOut


class MemberIn(SQLModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[int] = None
    joined_on: Optional[dt.date] = None
    left_on: Optional[dt.date] = None
    lang: Optional[Lang] = None
    password: Optional[str] = None


class CategoryIn(SQLModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    default_rule_json: Optional[dict[str, Any]] = None
    display_order: Optional[int] = None
    archived: Optional[bool] = None


class CategoryOut(SQLModel):
    id: int
    name: str
    icon: str
    color: str
    default_rule_json: Optional[dict[str, Any]]
    display_order: int
    archived: bool


class EntryIn(SQLModel):
    kind: EntryKind = EntryKind.expense
    date: dt.date
    amount_jpy: int
    payer_id: int
    title: str = ""
    note: str = ""
    category_id: Optional[int] = None
    to_member_id: Optional[int] = None
    member_ids: Optional[list[int]] = None
    rule: Optional[dict[str, Any]] = None
    period_start: Optional[dt.date] = None
    period_end: Optional[dt.date] = None
    bundle_id: Optional[int] = None


class EntryOut(SQLModel):
    id: int
    kind: EntryKind
    date: dt.date
    title: str
    amount_jpy: int
    category_id: Optional[int]
    payer_id: int
    to_member_id: Optional[int]
    period_id: Optional[int]
    period_label: Optional[str]
    period_start: Optional[dt.date]
    period_end: Optional[dt.date]
    bundle_id: Optional[int]
    split_rule_json: dict[str, Any]
    note: str
    created_by: Optional[int]
    created_at: dt.datetime
    updated_at: dt.datetime
    version: int
    #: 分摊快照 {member_id: 日元}。**这才是钱的真相**，规则只是为了还原界面
    shares: dict[str, int]


class PeriodOut(SQLModel):
    id: int
    label: str
    start_date: dt.date
    end_date: dt.date
    status: PeriodStatus
    closed_at: Optional[dt.datetime]


class BalancesOut(SQLModel):
    #: {member_id: 余额}。正数＝别人欠他，负数＝他欠别人。合计恒为 0
    balances: dict[str, int]


class SettingOut(SQLModel):
    key: str
    value: Any
    type: str
    note_zh: str
    note_ja: str
    options: Optional[list[Any]] = None
    min: Optional[int] = None
    max: Optional[int] = None


class SettingIn(SQLModel):
    value: Any
