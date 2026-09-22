"""开发用种子数据：三个室友 + 五个月的账。

    .venv/bin/python -m tools.seed_dev

密码统一 dev12345。**只在开发库上跑**，真用起来之前要删掉这些账号。

数据照着现在的设计铺，一眼能看到这些事：
  * 四张出过的账单 + 当前草稿。**出账日故意不规整**（5/30、7/2、7/28、8/30）——
    出账是「谁想起来点一下」，不是月底自动跑，账单日期得经得起这个
  * 每张单子的覆盖期从**上一次出账那天**算起，不是从这张单子里最早那笔算起
  * 前三张钱都转完了 → 「已结清」；最近那张只转了一笔 → 一个勾一个空
  * 固定费的日期一律是出账日（D30），日常开销保留真实日子
  * 水费两个月一收，只出现在 6 月和 8 月
  * 当前草稿的 燃气 / 水费 空着 → 面板给灰色参考值
  * 固定费全记在 Zen 头上 —— 一个人先垫一大笔，另外两个人转给他
  * 一笔带调整额（Zen 少担 1,000）、一笔 1:1:0（Zen 出差没参与）
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.auth import hash_password
from app.db import engine
from app.init_db import init_db
from app.models import Category, Entry, EntryKind, Member, Memo
from app.services import settings as settings_svc
from app.services.bill import cut_statement
from app.services.ledger import create_entry

PEOPLE = [("go", "Go", "#3d4785"), ("kan", "Kan", "#26a69a"), ("zen", "Zen", "#ef6c00")]
PASSWORD = "dev12345"


def d(month: int, day: int) -> dt.date:
    return dt.date(2026, month, day)


def utc(month: int, day: int) -> dt.datetime:
    """JST 正午对应的 naive UTC —— 时间戳统一存 UTC（见 models.now_utc）。"""
    return dt.datetime(2026, month, day, 3, 0)


def main() -> None:
    init_db()
    with Session(engine) as s:
        if s.exec(select(Member)).first():
            print("已经有成员了，跳过。要重来就删掉 data/nagaya.db")
            return

        members = []
        for order, (name, display, color) in enumerate(PEOPLE):
            m = Member(
                name=name, display_name=display, color=color, display_order=order,
                joined_on=d(4, 1), password_hash=hash_password(PASSWORD),
            )
            s.add(m)
            members.append(m)
        s.commit()
        for m in members:
            s.refresh(m)
        go, kan, zen = members

        # 不设 default_payer_id：留空时前端回落到「当前登录的人」，
        # 也就是「默认自己付」。真要全家从一个人卡上出，再去设置里指定

        cats = {c.name: c for c in s.exec(select(Category))}
        # 没点分类但写了备注时记到哪儿。名字不写死在代码里，放设置
        settings_svc.set_(s, "fallback_category_id", cats["其他"].id)
        # 房租按房间大小分（D12）：45,000 / 40,000 / 35,000。
        # 写成「同权 + 调整额」而不是固定金额 —— 均分是 40,000，Go 多担 5,000、
        # Zen 少担 5,000，加回去正好是那三个数。界面上已经没有固定金额模式了。
        rent = cats["房租"]
        rent.default_rule_json = {
            "mode": "ratio",
            "equal_weight": 1,
            "adjustments": {str(go.id): 5_000, str(zen.id): -5_000},
        }
        s.add(rent)
        s.commit()

        zen_less = {
            "mode": "ratio",
            "weights": {str(m.id): 1 for m in members},
            "adjustments": {str(zen.id): -1_000},
        }
        without_zen = {
            "mode": "ratio",
            "weights": {str(go.id): 1, str(kan.id): 1, str(zen.id): 0},
        }

        def add(kind, on, amount, cat_name, title, payer, **kw) -> Entry:
            # 收入不带分类：返现、給付金这些套不上「日用品/伙食」，写备注更清楚
            cat = cats[cat_name] if cat_name else None
            return create_entry(
                s, actor_id=go.id, kind=kind, on=on, amount=amount, payer_id=payer,
                category_id=cat.id if cat else None,
                category_rule=cat.default_rule_json if cat else None,
                title=title, **kw
            )

        def fixed(month: int, denki: int, gasu: int) -> None:
            """这个月的固定费。日期随便填，出账时会统一盖成出账日（D30）。

            **固定费一律记在 Zen 头上**：这屋里固定费都从同一张卡扣。
            于是每期都是「一个人先垫一大笔，另外两个人转给他」——
            转账方案、上期结转这些机制在示例数据里才有东西可演示。

            **固定费不带备注**：那一屏只有金额一个输入框，没有填备注的地方，
            示例数据里写了备注就等于演示一个界面上做不到的状态。
            """
            add(EntryKind.expense, d(month, 1), 120_000, "房租", "", zen.id)
            add(EntryKind.expense, d(month, 25), denki, "电费", "", zen.id)
            add(EntryKind.expense, d(month, 25), gasu, "燃气", "", zen.id)
            add(EntryKind.expense, d(month, 25), 5_500, "网费", "", zen.id)

        # ---------------------------------------------------------------- 5 月
        fixed(5, denki=7_800, gasu=4_600)
        add(EntryKind.expense, d(5, 3), 7_200, "伙食", "迎新烤肉", go.id)
        add(EntryKind.expense, d(5, 12), 2_480, "日用品", "洗衣液和卫生纸", zen.id)
        add(EntryKind.expense, d(5, 24), 3_900, "伙食", "披萨", kan.id)
        may = finish_cut(s, go.id, "5/30 出账", utc(5, 30))
        settle_plan(s, may, on=d(6, 2), at=utc(6, 2), how_many=None)

        # ---------------------------------------------------------------- 6 月
        fixed(6, denki=8_900, gasu=3_900)
        add(EntryKind.expense, d(6, 25), 11_800, "水费", "", zen.id)
        add(EntryKind.expense, d(6, 8), 1_780, "日用品", "垃圾袋和保鲜膜", kan.id)
        add(EntryKind.expense, d(6, 15), 6_400, "伙食", "烧烤", go.id, rule=zen_less)
        add(EntryKind.income, d(6, 21), -4_500, None, "电费返现", go.id)
        # 这一张拖到 7 月初才出 —— 覆盖期于是是 5/30〜7/2，跨了个月
        june = finish_cut(s, go.id, "7/2 出账", utc(7, 2))
        settle_plan(s, june, on=d(7, 4), at=utc(7, 4), how_many=None)

        # ---------------------------------------------------------------- 7 月
        fixed(7, denki=9_200, gasu=3_800)
        add(EntryKind.expense, d(7, 6), 1_380, "日用品", "卫生纸", zen.id)
        add(EntryKind.expense, d(7, 18), 6_400, "伙食", "烤肉", kan.id)
        add(EntryKind.expense, d(7, 25), 4_200, "伙食", "夏日凉面", go.id)
        july = finish_cut(s, go.id, "7/28 出账", utc(7, 28))
        settle_plan(s, july, on=d(8, 1), at=utc(8, 1), how_many=None)

        # ---------------------------------------------------------------- 8 月
        fixed(8, denki=10_400, gasu=3_200)
        add(EntryKind.expense, d(8, 25), 12_600, "水费", "", zen.id)
        add(EntryKind.expense, d(8, 12), 8_900, "伙食", "中元假期烤肉", go.id, rule=zen_less)
        add(EntryKind.expense, d(8, 20), 3_240, "日用品", "洗手液等", zen.id)
        add(EntryKind.income, d(8, 25), -3_000, None, "电费返现", go.id)
        august = finish_cut(s, go.id, "8/30 出账", utc(8, 30))
        # 只转了一笔 → 未结清，转账卡片上一个勾一个空
        settle_plan(s, august, on=d(9, 1), at=utc(9, 1), how_many=1)

        # ------------------------------------------------ 当前草稿：固定费填了一半
        add(EntryKind.expense, d(9, 1), 120_000, "房租", "", zen.id)
        add(EntryKind.expense, d(9, 18), 8_700, "电费", "", zen.id)
        add(EntryKind.expense, d(9, 19), 5_500, "网费", "", zen.id)
        # 燃气 和 水费 故意不填：面板要显示成灰色参考值，不是预填的真值
        add(EntryKind.expense, d(9, 3), 4_600, "伙食", "披萨（Zen 出差）", kan.id,
            rule=without_zen)
        add(EntryKind.expense, d(9, 10), 1_980, "日用品", "卫生纸", kan.id)
        add(EntryKind.expense, d(9, 14), 5_200, "伙食", "火锅食材", go.id)
        add(EntryKind.income, d(9, 20), -2_400, None, "乐天积分返现", kan.id)

        # 每项固定费谁垫，是**分类的常驻属性**。这屋里固定费全从 Zen 那张卡扣
        for name in ("房租", "电费", "燃气", "水费", "网费"):
            cats[name].default_payer_id = zen.id
            s.add(cats[name])

        # 备忘：固定费那几项各写一条，再加两条清单之外的
        notes = {
            "房租": "每月 1 号房东自动从 Go 的卡扣，别再手动转一次",
            "水费": "隔月收：6 / 8 / 10 月。单月那期是空的，不是忘了填",
            "网费": "合同 2027-03 到期，到期前一个月可以谈续约价",
        }
        for name, note in notes.items():
            cat = cats[name]
            cat.note = note
            s.add(cat)
        for i, (title, body) in enumerate([
            ("备用钥匙", "玄关鞋柜第二层，铁盒里"),
            ("垃圾袋", "买大号的，超市 B1 那家最便宜；周二周五早上收"),
        ]):
            s.add(Memo(title=title, body=body, display_order=i, created_by=go.id))
        s.commit()

        total = len(s.exec(select(Entry)).all())
        # **种子数据不值得备份。** 不关的话，起服务那一下就会给这个假账本备一份，
        # 产物和真备份同名同形躺在同一个目录里 —— 哪天恢复时挑「最新那份」，
        # 盖上去的是三个假室友。真实部署建的是全新库，设置走 SETTINGS_SPEC 的默认值
        # （backup_every_hours=24），不受这一行影响
        settings_svc.set_(s, "backup_every_hours", 0)

        print(f"建好 {len(PEOPLE)} 个成员（密码 {PASSWORD}）、4 张出过的账单、{total} 笔账")
        print("  出账日 5/30 / 7/2 / 7/28 / 8/30 —— 故意不规整")
        print("  前三张已结清；最近一张只转了一笔；当前草稿的 燃气 / 水费 空着")
        print("  自动备份已关掉 —— 种子数据不值得备份，也免得混进真备份里")


def finish_cut(s: Session, actor_id: int, label: str, at: dt.datetime):
    """出账，然后把出账时刻改成想要的那天 —— 种子要铺出一条像样的时间线。

    on 传出账那天：固定费的日期由它盖，账单的覆盖范围也跟着对。
    """
    st = cut_statement(s, actor_id=actor_id, label=label, on=at.date())
    st.cut_at = at
    if st.snapshot_json:
        snap = dict(st.snapshot_json)
        snap["cut_at"] = at.isoformat()
        st.snapshot_json = snap
    s.add(st)
    s.commit()
    s.refresh(st)
    return st


def settle_plan(s: Session, st, *, on: dt.date, at: dt.datetime, how_many: int | None) -> None:
    """照这张账单的转账方案记账。how_many=None 表示全转完。

    转账要落在**这张出账之后、下一张出账之前**，结算进度才认得出来
    （见 bill._settlement_progress）。所以 created_at 得跟着一起往回调。
    """
    plan = (st.snapshot_json or {}).get("transfers") or []
    for t in plan[: how_many if how_many is not None else len(plan)]:
        e = create_entry(
            s, actor_id=t["from_id"], kind=EntryKind.settlement, on=on,
            amount=t["amount"], payer_id=t["from_id"], to_member_id=t["to_id"],
        )
        e.created_at = at
        s.add(e)
    s.commit()


if __name__ == "__main__":
    main()
