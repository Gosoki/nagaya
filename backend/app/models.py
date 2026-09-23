"""数据模型 —— SPEC §5。

两条贯穿全局的设计：

* **entry_share 是落库快照，不是查询时现算。**
  第 4 个人搬进来、改默认比例、删分类，历史账单必须一个数字都不变。
* **支出 / 收入 / 转账共用 entry 一张表。**
  余额公式只有一条 `balance = Σ付出 − Σ应担`，不会出现「收入表忘了减」这种 bug。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from enum import Enum
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import JSON, Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel

#: 业务日期一律按日本时间算。部署到海外 VPS 也不会错位。
JST = ZoneInfo("Asia/Tokyo")


def now_utc() -> dt.datetime:
    """时间戳统一存 UTC（naive），只有业务日期才用 JST。"""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def today_jst() -> dt.date:
    return dt.datetime.now(JST).date()


def jst_date(ts: dt.datetime) -> dt.date:
    """存的是 naive UTC 时间戳，换算成日本时间的那一天。

    出账时间是个时刻，而账单上写的是日期 —— 日本时间凌晨出的账，
    按 UTC 算会退到前一天。
    """
    return ts.replace(tzinfo=dt.timezone.utc).astimezone(JST).date()


class EntryKind(str, Enum):
    expense = "expense"          # 支出：payer 垫钱，shares 是各人应担
    income = "income"            # 收入（返现等）：amount 为负，shares 也为负
    settlement = "settlement"    # 转账结清：payer 交钱给 to_member，share 全记在 to_member 头上


class Lang(str, Enum):
    zh = "zh"
    ja = "ja"


#: 全站可挑的颜色。**一组打底，另一组接着往后排** —— 不是两套色板。
#:
#: 分类那一组是底：界面上已经有的就是它（固定费那一列、流水里那些圆点）。
#: 头像的色卡从它开始排，不够了再往后补几个深一档的色相 —— 而不是另起一套。
#:
#: 建成员时从 MEMBER_COLORS 里挑一个**还没人用的**（见 routers/members.py、
#: tools/add_member.py）：都留默认灰的话，头像和账单每人行全靠颜色分辨谁是谁，
#: 三个人一个色就全废了；而新家建人走的是命令行/接口，不会有人先去挑颜色。
#:
#: 和前端那两份（frontend/src/palette.ts）是同一组，改一边记得改另一边
#: （frontend/test/palette-sync.spec.ts 钉着）。
CATEGORY_COLORS = [
    "#5c6bc0",  # 靛
    "#26a69a",  # 青
    "#ffa726",  # 琥珀
    "#ef5350",  # 红
    "#ab47bc",  # 紫
    "#29b6f6",  # 天蓝
    "#66bb6a",  # 绿
    "#ec407a",  # 粉
    "#8d6e63",  # 棕
    "#78909c",  # 蓝灰
]

#: 头像那一组：先用界面上已经有的（上面那十个），再往后补几个深一档的
MEMBER_COLORS = CATEGORY_COLORS + [
    "#3d4785",  # 靛（品牌色）
    "#00838f",  # 蓝绿
    "#c62828",  # 红
    "#ef6c00",  # 橙
    "#2e7d32",  # 绿
    "#ad1457",  # 玫红
]


def free_color(used: Iterable[str]) -> str:
    """给新人发一个**还没人用的**头像色。

    按人数取模的老做法会撞：删过人、或者有人自己挑过色之后，
    新来的很可能拿到一个已经在用的颜色 —— 而头像圆点、账单每人行
    全靠颜色分辨谁是谁。色板用完了才从头轮。
    """
    taken = {c.lower() for c in used if c}
    for color in MEMBER_COLORS:
        if color.lower() not in taken:
            return color
    return MEMBER_COLORS[len(taken) % len(MEMBER_COLORS)]
class Member(SQLModel, table=True):
    """成员。退出的人不删，只填 left_on —— 历史账要能追溯到人。"""

    __tablename__ = "member"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, description="登录名")
    display_name: str = Field(description="界面上显示的名字")
    color: str = Field(default="#888888", description="头像/图表配色（建人时挑一个还没人用的，见 MEMBER_COLORS）")
    display_order: int = Field(default=0, index=True, description="固定顺序，也是分摊余数平局时的排序依据")
    joined_on: dt.date = Field(default_factory=today_jst)
    left_on: Optional[dt.date] = Field(default=None, description="退出日；留空＝在籍")
    password_hash: str = ""
    lang: Lang = Field(default=Lang.zh)
    avatar: Optional[bytes] = Field(
        default=None,
        sa_column=Column(LargeBinary),
        description=(
            "头像图片（WebP）。**存库里不存目录**：压完才几 KB，三个人加起来不到 50KB，"
            "而备份是 VACUUM INTO 出一份库文件 —— 放目录里的话备份里就没有头像，得再管一套备份和权限。"
            "（**别只拷 nagaya.db**：开着 WAL，没 checkpoint 的数据全在 nagaya.db-wal 里，"
            "实测主文件只有 4096 字节、单拷出来是个零张表的空库。）"
        ),
    )
    avatar_version: int = Field(default=0, description="改一次加一，前端拿它做缓存键")
    created_at: dt.datetime = Field(default_factory=now_utc)

    def is_active(self, on: dt.date | None = None) -> bool:
        """某天是否在籍。新建账目时默认参与人＝当天在籍的人。"""
        on = on or today_jst()
        if on < self.joined_on:
            return False
        return self.left_on is None or on <= self.left_on


class Category(SQLModel, table=True):
    """分类。词表进数据库、面板可改，代码里不写死（房租/电/煤/水/网/日用品…）。"""

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
    monthly: bool = Field(
        default=False,
        index=True,
        description=(
            "每月一次的固定项（房租/电费/燃气/水费/网费）。"
            "这类不在日常「记一笔」的分类网格里占位置，改到出账单那一页顺手填。"
            "**这是个用户可改的字段，不是代码里的名字列表** —— 以后加「停车位」"
            "也能自己勾上。"
        ),
    )
    display_order: int = Field(default=0, index=True)
    archived: bool = Field(default=False, index=True)
    default_payer_id: Optional[int] = Field(
        default=None,
        foreign_key="member.id",
        description=(
            "这一项固定费默认谁垫。**这是分类的常驻属性，不是每期临时决定的** —— "
            "房租永远从同一张卡扣，网费永远是另一个人。留空则回退到全局的「默认垫付人」，"
            "再没有就算当前登录的人。"
            "不这么定的话，固定费面板上就是「谁填的算谁」：别人刷的卡被随手填进去，"
            "账本当场错一整笔房租的钱，而屏幕上一点提示都没有。"
        ),
    )
    same_as_last: bool = Field(
        default=False,
        description=(
            "这一项每期金额都一样（房租、网费这种）：固定费面板那一行上出现「照上期」，"
            "点一下按上期的金额记上（出账对话框里也有一个勾）。"
            "**默认关着**，而且必须一项一项地开 —— 「上期金额不许预填」这条规矩"
            "就是为了防「某个月忘了改，带着上月的电费把账单发出去」。"
            "电费燃气水费恰恰是每期都不一样的，给它们开这个等于把那条规矩废掉。"
        ),
    )
    note: str = Field(
        default="",
        description=(
            "这一项的常驻备忘：什么时候收、从谁的卡扣、合同哪天到期。"
            "**跟着分类走，不跟着某一笔账走** —— 「水费隔月收」这种事每期都成立，"
            "写在某一笔的备注里，下个月就找不着了。"
        ),
    )


class RequestKey(SQLModel, table=True):
    """「记一笔」的幂等键：前端每次记账带一个随机串，同一个串只记一次。

    离线草稿的毛病在这儿：请求其实已经到了后端、账也记上了，只是响应在回程丢了
    （电梯里、地铁换乘）—— 前端只看到「连不上」，把这笔存成草稿，补交时再记一遍，
    账本里就是两笔一模一样的钱。补交时带着同一个键，后端认出来直接还给它原来那笔。

    **是张新表，不是 entry 上的一列**：写这张表的时候还没切 Alembic，不能给老表加列；
    现在的迁移基线里有它，老备份恢复时会自动补上。
    """

    __tablename__ = "request_key"

    key: str = Field(primary_key=True, max_length=64)
    entry_id: int = Field(foreign_key="entry.id")
    created_at: dt.datetime = Field(default_factory=now_utc)


class MemberPref(SQLModel, table=True):
    """个人偏好（深浅色、主题色）。**跟着账号走**：换台手机登录，还是自己挑的那一套。

    一人一项一行，不在 member 上加列：以后多一项偏好就是多一个键，不用写迁移。
    前端本机那份只是缓存：首帧要靠它在 JS 起来之前就上色。
    """

    __tablename__ = "member_pref"

    member_id: int = Field(foreign_key="member.id", primary_key=True)
    key: str = Field(primary_key=True, max_length=32)
    value: str = Field(max_length=32)
    updated_at: dt.datetime = Field(default_factory=now_utc)


class AppIcon(SQLModel, table=True):
    """这屋自己的 App 图标（主屏那个、页签那个小的）。只有一行，id 恒为 1。

    **存在库里而不是磁盘上**：备份走的是 VACUUM INTO，只覆盖数据库 ——
    图标放磁盘的话，恢复一份备份之后图标还是旧的，而它恰恰是
    「这是哪个屋的账本」的标志。
    只存一张 512 的母版，各尺寸取的时候现缩（一年也取不了几次）。
    """

    __tablename__ = "app_icon"

    id: Optional[int] = Field(default=1, primary_key=True)
    png: bytes = Field(default=b"", sa_column=Column(LargeBinary))
    updated_at: dt.datetime = Field(default_factory=now_utc)


class Memo(SQLModel, table=True):
    """自己加的备忘条目。

    固定费那几项的备忘写在 Category.note 上（它们本来就是一份现成的清单）；
    这张表装的是清单之外的东西 —— 备用钥匙放哪、垃圾袋买哪种、房东电话。
    """

    __tablename__ = "memo"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(description="条目名")
    body: str = Field(default="", description="正文")
    display_order: int = Field(default=0, index=True)
    created_at: dt.datetime = Field(default_factory=now_utc)
    updated_at: dt.datetime = Field(default_factory=now_utc)
    created_by: Optional[int] = Field(default=None, foreign_key="member.id")


class Statement(SQLModel, table=True):
    """一张已经出过的账单。

    **线是人点出来的，不是日历划的**：点「出账单」的那一刻，把当时所有还没出账的
    支出/收入/转账一次性归到这张单子上，冻结一份快照，之后再记的账自动进下一张。

    这么做去掉了一整套按日历归期的机制 —— 起算日、月份边界、「这笔落进了哪一期」、
    改起算日导致账期重叠 —— 那些问题全是日历边界自己造出来的。

    还没出账的账目 `entry.statement_id IS NULL`，它们合起来就是「当前这张草稿账单」。
    """

    __tablename__ = "statement"

    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(index=True, description="出账时存空串（接口不收名字），展示名由前端按 cut_at 渲染（src/statement.ts）；老库里的「M/D 出账」前端照样认")
    cut_at: dt.datetime = Field(default_factory=now_utc, index=True, description="划线的那一刻")
    #: 覆盖期的**起点是上一次出账那天**，不是这张单子里最早那笔的日期。
    #: 「7 月那张从 7/2 开始」是错觉 —— 7/1 只是没人花钱，它管的是 6/30 出账之后的一切。
    #: 头一张没有上一次，才从第一笔算起。见 bill._covers_from
    covers_from: Optional[dt.date] = Field(default=None, description="覆盖期起点：上次出账那天")
    covers_to: Optional[dt.date] = Field(default=None, description="这张单子里最晚一笔的日期")
    cut_by: Optional[int] = Field(default=None, foreign_key="member.id")
    #: 出账**不锁定任何东西**（D24）。余额是全局累计的，事后改一笔已出账的账，
    #: 差额会原样出现在下一张的「上期结转」里，钱不会算错 —— 所以不需要「关账」这道门。
    #: 需要的只是把「这一期在出账后被改过」显示出来，让结转解释得清。
    #: 曾短暂加过「锁 + 解锁」，多一道门却保护不了钱，已经整套删掉了。
    snapshot_json: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="出账那一刻冻结的账单，保证以后还能原样重现「当初发给室友的那张」",
    )


class Entry(SQLModel, table=True):
    """一笔账（支出 / 收入 / 转账三合一）。"""

    __tablename__ = "entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: EntryKind = Field(default=EntryKind.expense, index=True)
    date: dt.date = Field(index=True, description="费用发生日 / 转账日。归哪张账单看 statement_id，不看它；固定费出账时盖成出账日（D30）")
    title: str = Field(default="", description="选填，粗放写法即可（「日用品」就够）")
    amount_jpy: int = Field(description="整数日元。收入为负。禁 float")

    category_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)
    payer_id: int = Field(foreign_key="member.id", index=True, description="垫付人 / 收款人；转账时＝转出人")
    to_member_id: Optional[int] = Field(
        default=None, foreign_key="member.id", description="仅转账：转入人"
    )

    #: 归到哪张账单。**None ＝ 还没出账**，和其它 None 一起构成「当前这张草稿账单」。
    #: 出账时一次性打上，之后不再变 —— 账单是对「那一刻」的陈述。
    statement_id: Optional[int] = Field(default=None, foreign_key="statement.id", index=True)

    split_rule_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="原始规则，为了编辑时能把界面还原回去。真正的钱以 entry_share 为准",
    )
    note: str = ""

    created_by: Optional[int] = Field(default=None, foreign_key="member.id")
    created_at: dt.datetime = Field(default_factory=now_utc)
    updated_at: dt.datetime = Field(default_factory=now_utc)
    version: int = Field(default=1, description="乐观锁：两个人同时改一笔账时挡住覆盖")
    # **不建索引。** 几乎每一行都是 NULL，而 SQLite 把 `IS NULL` 当等值条件，
    # 有这个索引就拿它开路 —— 于是「最近 500 笔」要先把整本账按它扫一遍再排序
    # （5 年规模 9.6ms → 去掉之后走日期索引 0.7ms）。ANALYZE 也救不回来（实测）
    deleted_at: Optional[dt.datetime] = Field(default=None, description="软删，进回收站")


class EntryShare(SQLModel, table=True):
    """分摊快照。**这张表是整个账本的地基**：算完就固化，之后谁都不许倒着改。

    Σ amount_jpy == entry.amount_jpy，由应用在写入时断言。
    """

    __tablename__ = "entry_share"
    __table_args__ = (UniqueConstraint("entry_id", "member_id", name="uq_share_entry_member"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    # entry_id 不单独建索引：上面那个 (entry_id, member_id) 唯一约束自带的索引就能按它查
    entry_id: int = Field(foreign_key="entry.id")
    member_id: int = Field(foreign_key="member.id", index=True)
    amount_jpy: int = Field(description="这个人在这笔账里应担多少。可负")


class Setting(SQLModel, table=True):
    """key-value 配置。每一项的类型、范围、中日文说明登记在 settings_spec.py，接口从那儿拿，不进库。"""

    __tablename__ = "setting"

    key: str = Field(primary_key=True)
    value_json: Any = Field(default=None, sa_column=Column(JSON))
    updated_at: dt.datetime = Field(default_factory=now_utc)


class AuditLog(SQLModel, table=True):
    """谁在什么时候把哪条账改成了什么。钱的事必须留痕（SPEC F12）。"""

    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    at: dt.datetime = Field(default_factory=now_utc, index=True)
    member_id: Optional[int] = Field(default=None, foreign_key="member.id", index=True)
    action: str = Field(index=True, description="create / update / delete / restore / cut_statement / password")
    target_table: str = Field(index=True)
    target_id: Optional[int] = Field(default=None, index=True)
    before_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    after_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
