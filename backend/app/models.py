"""数据模型 —— SPEC §5。

两条贯穿全局的设计：

* **entry_share 是落库快照，不是查询时现算。**
  第 4 个人搬进来、改默认比例、删分类，历史账单必须一个数字都不变。
* **支出 / 收入 / 转账共用 entry 一张表。**
  余额公式只有一条 `balance = Σ付出 − Σ应担`，不会出现「收入表忘了减」这种 bug。
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

#: 业务日期一律按日本时间算。部署到海外 VPS 也不会错位。
JST = ZoneInfo("Asia/Tokyo")


def now_utc() -> dt.datetime:
    """时间戳统一存 UTC（naive），只有业务日期才用 JST。"""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def today_jst() -> dt.date:
    return dt.datetime.now(JST).date()


class EntryKind(str, Enum):
    expense = "expense"          # 支出：payer 垫钱，shares 是各人应担
    income = "income"            # 收入（返现等）：amount 为负，shares 也为负
    settlement = "settlement"    # 转账结清：payer 交钱给 to_member，share 全记在 to_member 头上


class PeriodStatus(str, Enum):
    open = "open"
    closed = "closed"


class Lang(str, Enum):
    zh = "zh"
    ja = "ja"


class Member(SQLModel, table=True):
    """成员。退出的人不删，只填 left_on —— 历史账要能追溯到人。"""

    __tablename__ = "member"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, description="登录名")
    display_name: str = Field(description="界面上显示的名字")
    color: str = Field(default="#888888", description="头像/图表配色")
    display_order: int = Field(default=0, index=True, description="固定顺序，也是分摊余数平局时的排序依据")
    joined_on: dt.date = Field(default_factory=today_jst)
    left_on: Optional[dt.date] = Field(default=None, description="退出日；留空＝在籍")
    password_hash: str = ""
    lang: Lang = Field(default=Lang.zh)
    created_at: dt.datetime = Field(default_factory=now_utc)

    def is_active(self, on: dt.date | None = None) -> bool:
        """某天是否在籍。新建账目时默认参与人＝当天在籍的人。"""
        on = on or today_jst()
        if on < self.joined_on:
            return False
        return self.left_on is None or on <= self.left_on


class Category(SQLModel, table=True):
    """分类。词表进数据库、面板可改，代码里不写死（家賃/电/煤/水/网/日用品…）。"""

    __tablename__ = "category"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, description="分类名，用户自己录什么就显示什么，不做双语")
    icon: str = Field(default="receipt_long", description="Quasar 图标名")
    color: str = Field(default="#607d8b")
    default_rule_json: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="该分类的默认分摊规则（SPEC §4.7 第 2 层）。留空则用全局默认",
    )
    display_order: int = Field(default=0, index=True)
    archived: bool = Field(default=False, index=True)


class Period(SQLModel, table=True):
    """账期。按费用发生日归期；关账前一直 open，关账后明细锁定。"""

    __tablename__ = "period"
    __table_args__ = (UniqueConstraint("start_date", name="uq_period_start"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(index=True, unique=True, description="'2026-09'，取结束日所在月")
    start_date: dt.date = Field(index=True)
    end_date: dt.date = Field(index=True)
    status: PeriodStatus = Field(default=PeriodStatus.open, index=True)
    closed_at: Optional[dt.datetime] = None
    closed_by: Optional[int] = Field(default=None, foreign_key="member.id")
    snapshot_json: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="关账时冻结的余额/成员/明细，保证这张账单以后还能原样重现",
    )


class Bundle(SQLModel, table=True):
    """光熱費套餐：一次录入电/煤/水/网多项，挂同一个 bundle 方便一起看、一起改。"""

    __tablename__ = "bundle"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    period_id: Optional[int] = Field(default=None, foreign_key="period.id", index=True)
    created_at: dt.datetime = Field(default_factory=now_utc)


class Entry(SQLModel, table=True):
    """一笔账（支出 / 收入 / 转账三合一）。"""

    __tablename__ = "entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: EntryKind = Field(default=EntryKind.expense, index=True)
    date: dt.date = Field(index=True, description="费用发生日 / 转账日。归期只看它")
    title: str = Field(default="", description="选填，粗放写法即可（「日用品」就够）")
    amount_jpy: int = Field(description="整数日元。收入为负。禁 float")

    category_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)
    payer_id: int = Field(foreign_key="member.id", index=True, description="垫付人 / 收款人；转账时＝转出人")
    to_member_id: Optional[int] = Field(
        default=None, foreign_key="member.id", description="仅转账：转入人"
    )

    # 账期显式存，不靠日期现算。因为「10/15 结的是 9 月的账」这条规则
    # 光看日期推不出来（SPEC §4.6）。默认按日期落，转账则挂到最早的未关账期。
    period_id: Optional[int] = Field(default=None, foreign_key="period.id", index=True)

    # 仅用于账单上标注「含 7–8 月水费」「10月分 家賃」，不参与任何计算（SPEC §4.4）
    period_start: Optional[dt.date] = None
    period_end: Optional[dt.date] = None

    bundle_id: Optional[int] = Field(default=None, foreign_key="bundle.id", index=True)

    split_rule_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="原始规则，为了编辑时能把界面还原回去。真正的钱以 entry_share 为准",
    )
    note: str = ""
    receipt_path: Optional[str] = None

    created_by: Optional[int] = Field(default=None, foreign_key="member.id")
    created_at: dt.datetime = Field(default_factory=now_utc)
    updated_at: dt.datetime = Field(default_factory=now_utc)
    version: int = Field(default=1, description="乐观锁：两个人同时改一笔账时挡住覆盖")
    deleted_at: Optional[dt.datetime] = Field(default=None, index=True, description="软删，进回收站")


class EntryShare(SQLModel, table=True):
    """分摊快照。**这张表是整个账本的地基**：算完就固化，之后谁都不许倒着改。

    Σ amount_jpy == entry.amount_jpy，由应用在写入时断言。
    """

    __tablename__ = "entry_share"
    __table_args__ = (UniqueConstraint("entry_id", "member_id", name="uq_share_entry_member"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    entry_id: int = Field(foreign_key="entry.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    amount_jpy: int = Field(description="这个人在这笔账里应担多少。可负")


class Template(SQLModel, table=True):
    """模板：家賃这种固定额一键生成；光熱費套餐存 items_json。"""

    __tablename__ = "template"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: EntryKind = Field(default=EntryKind.expense)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    payer_default_id: Optional[int] = Field(default=None, foreign_key="member.id")
    amount_default: Optional[int] = Field(default=None, description="家賃这种固定额")
    rule_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    items_json: Optional[list[dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON), description="套餐模板：电/煤/水/网各一项"
    )
    display_order: int = Field(default=0)
    archived: bool = Field(default=False)


class Setting(SQLModel, table=True):
    """key-value 配置。note 存中日文说明，面板逐项渲染（见 settings_spec.py）。"""

    __tablename__ = "setting"

    key: str = Field(primary_key=True)
    value_json: Any = Field(default=None, sa_column=Column(JSON))
    note_zh: str = ""
    note_ja: str = ""
    updated_at: dt.datetime = Field(default_factory=now_utc)


class AuditLog(SQLModel, table=True):
    """谁在什么时候把哪条账改成了什么。钱的事必须留痕（SPEC F12）。"""

    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    at: dt.datetime = Field(default_factory=now_utc, index=True)
    member_id: Optional[int] = Field(default=None, foreign_key="member.id", index=True)
    action: str = Field(index=True, description="create / update / delete / restore / close_period / reopen_period …")
    target_table: str = Field(index=True)
    target_id: Optional[int] = Field(default=None, index=True)
    before_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    after_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
