"""API 的出入参。后端只返数据和枚举 key，**不返界面文案**（文案全在前端 vue-i18n）。"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import field_validator
from sqlmodel import SQLModel

from app.models import EntryKind, Lang


def _no_bool_amount(v: Any) -> Any:
    """`amount_jpy: true` 会被 Pydantic 悄悄转成 1，入库成 ¥1。

    服务层那句 `isinstance(amount, bool)` 挡不住它 —— 等它到服务层时已经是 int 了。
    要挡只能挡在转换之前。
    """
    if isinstance(v, bool):
        raise ValueError("金额不能是 true/false")
    return v


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
    #: 头像，`data:image/webp;base64,...`。**随成员一起下发**，不单开一个图片地址：
    #: `<img>` 带不了 Bearer token，做成公开端点等于在局域网上开个口子；
    #: 而且压完才几 KB，跟着成员走还能进本地缓存，离线时头像照样在
    avatar: Optional[str] = None
    avatar_version: int = 0


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
    #: 改自己的密码时要先验一遍旧的。手机放桌上被人顺手改掉，自己就进不来了
    old_password: Optional[str] = None


class CategoryIn(SQLModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    default_rule_json: Optional[dict[str, Any]] = None
    monthly: Optional[bool] = None
    display_order: Optional[int] = None
    archived: Optional[bool] = None
    note: Optional[str] = None
    default_payer_id: Optional[int] = None
    same_as_last: Optional[bool] = None


class CategoryOut(SQLModel):
    id: int
    name: str
    icon: str
    color: str
    default_rule_json: Optional[dict[str, Any]]
    monthly: bool
    display_order: int
    archived: bool
    note: str
    default_payer_id: Optional[int]
    same_as_last: bool


class MemoIn(SQLModel):
    title: Optional[str] = None
    body: Optional[str] = None
    display_order: Optional[int] = None


class MemoOut(SQLModel):
    id: int
    title: str
    body: str
    display_order: int
    updated_at: dt.datetime


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
    bundle_id: Optional[int] = None

    _amount_not_bool = field_validator("amount_jpy", mode="before")(_no_bool_amount)


class EntryPatch(SQLModel):
    """改一笔账。**每个字段都可选** —— 没传的就不动。

    这不是洁癖：原来 PATCH 复用 EntryIn（payer_id 是必填），于是固定费面板改个金额
    也被迫带上 payer_id，而那一屏根本没显示过付款人。结果是 Kan 垫的电费被 Go 改一下
    金额就算到了 Go 头上，两人余额各错一个电费钱，零提示。
    """

    kind: Optional[EntryKind] = None
    date: Optional[dt.date] = None
    amount_jpy: Optional[int] = None
    payer_id: Optional[int] = None
    title: Optional[str] = None
    note: Optional[str] = None
    category_id: Optional[int] = None
    to_member_id: Optional[int] = None
    member_ids: Optional[list[int]] = None
    rule: Optional[dict[str, Any]] = None
    bundle_id: Optional[int] = None

    _amount_not_bool = field_validator("amount_jpy", mode="before")(_no_bool_amount)


class EntryOut(SQLModel):
    id: int
    kind: EntryKind
    date: dt.date
    title: str
    amount_jpy: int
    category_id: Optional[int]
    payer_id: int
    to_member_id: Optional[int]
    statement_id: Optional[int]
    statement_label: Optional[str]
    bundle_id: Optional[int]
    split_rule_json: dict[str, Any]
    note: str
    created_by: Optional[int]
    created_at: dt.datetime
    updated_at: dt.datetime
    version: int
    #: 分摊快照 {member_id: 日元}。**这才是钱的真相**，规则只是为了还原界面
    shares: dict[str, int]


class StatementOut(SQLModel):
    id: int
    label: str
    cut_at: dt.datetime
    covers_from: Optional[dt.date]
    covers_to: Optional[dt.date]
    cut_by: Optional[int]
    #: 列表页要在每一行上直接显示金额和结清状态，不然得为每张单子再拉一次账单接口。
    #: 金额取**实时**值（出账后改过就显示改后的），跟详情页对得上。
    total_expense: int = 0
    settled: bool = False


class BalancesOut(SQLModel):
    #: {member_id: 余额}。正数＝别人欠他，负数＝他欠别人。合计恒为 0
    balances: dict[str, int]


class SettingOut(SQLModel):
    key: str
    value: Any
    type: str
    #: 通用面板里不渲染它 —— 有专门的卡片管（比如 App 名字和图标）。
    #: 仍然照常返回：那张卡片要读它的值
    hidden: bool = False
    note_zh: str
    note_ja: str
    options: Optional[list[Any]] = None
    min: Optional[int] = None
    max: Optional[int] = None


class SettingIn(SQLModel):
    value: Any
