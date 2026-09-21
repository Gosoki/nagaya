"""开发用种子数据：三个室友 + 五个月的账。

    .venv/bin/python -m tools.seed_dev

密码统一 dev12345。**只在开发库上跑**，真用起来之前要删掉这些账号。

数据照着现在的设计铺，一眼能看到这些事：
  * 5〜8 月各出过一张账单，9 月是当前草稿
  * 5/6/7 月三张钱都转完了 → 「已结清」；8 月那张只转了一笔 → 一个勾一个空
  * 固定费的日期一律是出账日（D30），日常开销保留真实日子
  * 水道两个月一收，只出现在 6 月和 8 月，带计费期间 → 账单上标「含 4〜5月分」
  * 当前草稿的 ガス / 水道 空着 → 面板给灰色参考值
  * 一笔带调整额（Zen 少担 1,000）、一笔 1:1:0（Zen 出差没参与）
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.auth import hash_password
from app.db import engine
from app.init_db import init_db
from app.models import Category, Entry, EntryKind, Member
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

        settings_svc.set_(s, "default_payer_id", go.id)
        settings_svc.set_(s, "settle_due_day", 10)

        cats = {c.name: c for c in s.exec(select(Category))}
        # 家賃按房间大小分（D12）：45,000 / 40,000 / 35,000。
        # 写成「同权 + 调整额」而不是固定金额 —— 均分是 40,000，Go 多担 5,000、
        # Zen 少担 5,000，加回去正好是那三个数。界面上已经没有固定金额模式了。
        rent = cats["家賃"]
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
            # 收入不带分类：返现、給付金这些套不上「日用品/食費」，写备注更清楚
            cat = cats[cat_name] if cat_name else None
            return create_entry(
                s, actor_id=go.id, kind=kind, on=on, amount=amount, payer_id=payer,
                category_id=cat.id if cat else None,
                category_rule=cat.default_rule_json if cat else None,
                title=title, **kw
            )

        def fixed(month: int, denki: int, gasu: int, *, denki_note: str = "") -> None:
            """这个月的固定费。日期随便填，出账时会统一盖成出账日（D30）。"""
            add(EntryKind.expense, d(month, 1), 120_000, "家賃", "", go.id)
            add(EntryKind.expense, d(month, 25), denki, "電気", denki_note, go.id)
            add(EntryKind.expense, d(month, 25), gasu, "ガス", "", go.id)
            add(EntryKind.expense, d(month, 25), 5_500, "ネット", "", kan.id)

        # ---------------------------------------------------------------- 5 月
        fixed(5, denki=7_800, gasu=4_600)
        add(EntryKind.expense, d(5, 3), 7_200, "食費", "歓迎会の焼肉", go.id)
        add(EntryKind.expense, d(5, 12), 2_480, "日用品", "洗剤とトイレットペーパー", zen.id)
        add(EntryKind.expense, d(5, 24), 3_900, "食費", "ピザ", kan.id)
        may = finish_cut(s, go.id, "5/31 出账", utc(5, 31))
        settle_plan(s, may, on=d(6, 2), at=utc(6, 2), how_many=None)

        # ---------------------------------------------------------------- 6 月
        fixed(6, denki=8_900, gasu=3_900)
        add(EntryKind.expense, d(6, 25), 11_800, "水道", "4〜5月分", go.id,
            period_start=d(4, 1), period_end=d(5, 31))
        add(EntryKind.expense, d(6, 8), 1_780, "日用品", "ゴミ袋とラップ", kan.id)
        add(EntryKind.expense, d(6, 15), 6_400, "食費", "BBQ", go.id, rule=zen_less)
        add(EntryKind.income, d(6, 21), -4_500, None, "電気代キャッシュバック", go.id)
        june = finish_cut(s, go.id, "6/30 出账", utc(6, 30))
        settle_plan(s, june, on=d(7, 2), at=utc(7, 2), how_many=None)

        # ---------------------------------------------------------------- 7 月
        fixed(7, denki=9_200, gasu=3_800)
        add(EntryKind.expense, d(7, 6), 1_380, "日用品", "トイレットペーパー", zen.id)
        add(EntryKind.expense, d(7, 18), 6_400, "食費", "焼肉", kan.id)
        add(EntryKind.expense, d(7, 25), 4_200, "食費", "そうめん大会", go.id)
        july = finish_cut(s, go.id, "7/31 出账", utc(7, 31))
        settle_plan(s, july, on=d(8, 3), at=utc(8, 3), how_many=None)

        # ---------------------------------------------------------------- 8 月
        fixed(8, denki=10_400, gasu=3_200, denki_note="エアコン代")
        add(EntryKind.expense, d(8, 25), 12_600, "水道", "6〜7月分", go.id,
            period_start=d(6, 1), period_end=d(7, 31))
        add(EntryKind.expense, d(8, 12), 8_900, "食費", "お盆の焼肉", go.id, rule=zen_less)
        add(EntryKind.expense, d(8, 20), 3_240, "日用品", "ハンドソープほか", zen.id)
        add(EntryKind.income, d(8, 25), -3_000, None, "電気代キャッシュバック", go.id)
        august = finish_cut(s, go.id, "8/31 出账", utc(8, 31))
        # 只转了一笔 → 未结清，转账卡片上一个勾一个空
        settle_plan(s, august, on=d(9, 2), at=utc(9, 2), how_many=1)

        # ------------------------------------------------ 当前草稿：固定费填了一半
        add(EntryKind.expense, d(9, 1), 120_000, "家賃", "", go.id)
        add(EntryKind.expense, d(9, 18), 8_700, "電気", "", go.id)
        add(EntryKind.expense, d(9, 19), 5_500, "ネット", "", kan.id)
        # ガス 和 水道 故意不填：面板要显示成灰色参考值，不是预填的真值
        add(EntryKind.expense, d(9, 3), 4_600, "食費", "ピザ（Zen 出張中）", kan.id,
            rule=without_zen)
        add(EntryKind.expense, d(9, 10), 1_980, "日用品", "トイレットペーパー", kan.id)
        add(EntryKind.expense, d(9, 14), 5_200, "食費", "鍋の材料", go.id)
        add(EntryKind.income, d(9, 20), -2_400, None, "楽天ポイント還元", kan.id)

        total = len(s.exec(select(Entry)).all())
        print(f"建好 {len(PEOPLE)} 个成员（密码 {PASSWORD}）、4 张出过的账单、{total} 笔账")
        print("  5/6/7 月已结清；8 月只转了一笔；当前草稿的 ガス / 水道 空着")


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
