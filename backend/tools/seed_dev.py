"""开发用种子数据：三个室友 + 两张出过的账单 + 一张当前草稿。

    .venv/bin/python -m tools.seed_dev

密码统一 dev12345。**只在开发库上跑**，真用起来之前要删掉这些账号。

数据是照着现在的设计铺的，一眼能看到这几件事：
  * 7 月那张已经全部转完钱 → 「已结清」
  * 8 月那张只转了一笔 → 未结清，转账卡片上一个勾一个空
  * 当前草稿里固定费只填了一半，ガス / 水道 空着 → 面板给灰色参考值
  * 水道带计费期间 7/1〜8/31 → 账单上标「含 7〜8月分」
  * 一笔带调整额（Zen 少担 1,000）、一笔 1:1:0（Zen 出差没参与）
  * 上一张没转完的钱变成下一张的「上期结转」
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
        # 家賃走固定金额（D12：房间大小不同，不是比例）
        rent = cats["家賃"]
        rent.default_rule_json = {
            "mode": "exact",
            "exact": {str(go.id): 45_000, str(kan.id): 40_000, str(zen.id): 35_000},
        }
        s.add(rent)
        s.commit()

        equal_minus_zen = {"mode": "ratio", "weights": {str(go.id): 1, str(kan.id): 1, str(zen.id): 0}}
        zen_pays_less = {
            "mode": "ratio",
            "weights": {str(m.id): 1 for m in members},
            "adjustments": {str(zen.id): -1_000},
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

        # ---------------------------------------------- 第一张：7 月分，全部转完
        add(EntryKind.expense, d(7, 1), 120_000, "家賃", "", go.id)
        add(EntryKind.expense, d(7, 10), 1_380, "日用品", "トイレットペーパー", zen.id)
        add(EntryKind.expense, d(7, 18), 6_400, "食費", "焼肉", kan.id)
        add(EntryKind.expense, d(7, 28), 9_200, "電気", "", go.id)
        add(EntryKind.expense, d(7, 28), 3_800, "ガス", "", go.id)
        add(EntryKind.expense, d(7, 28), 5_500, "ネット", "", kan.id)
        add(EntryKind.expense, d(8, 2), 2_180, "日用品", "洗剤とゴミ袋", go.id)
        july = finish_cut(s, go.id, "8/5 出账", utc(8, 5))

        # 照着方案全转完 → 这张显示「已结清」
        settle_plan(s, july, on=d(8, 6), at=utc(8, 6), how_many=None)

        # ---------------------------------------------- 第二张：8 月分，只转了一笔
        add(EntryKind.expense, d(8, 5), 120_000, "家賃", "", go.id)
        add(EntryKind.expense, d(8, 12), 8_900, "食費", "お盆の焼肉", go.id, rule=zen_pays_less)
        add(EntryKind.expense, d(8, 20), 3_240, "日用品", "ハンドソープほか", zen.id)
        add(EntryKind.expense, d(8, 28), 10_400, "電気", "エアコン代", go.id)
        add(EntryKind.expense, d(8, 28), 3_200, "ガス", "", go.id)
        add(EntryKind.expense, d(8, 28), 5_500, "ネット", "", kan.id)
        add(EntryKind.income, d(8, 25), -3_000, None, "電気代キャッシュバック", go.id)
        add(EntryKind.expense, d(8, 28), 12_600, "水道", "7〜8月分", go.id,
            period_start=d(7, 1), period_end=d(8, 31))
        august = finish_cut(s, go.id, "8/31 出账", utc(8, 31))

        # 只转了一笔 → 未结清，转账卡片上一个勾一个空
        settle_plan(s, august, on=d(9, 2), at=utc(9, 2), how_many=1)

        # ---------------------------------------------- 当前草稿：固定费只填了一半
        add(EntryKind.expense, d(9, 1), 120_000, "家賃", "", go.id)
        add(EntryKind.expense, d(9, 3), 4_600, "食費", "ピザ（Zen 出張中）", kan.id,
            rule=equal_minus_zen)
        add(EntryKind.expense, d(9, 10), 1_980, "日用品", "トイレットペーパー", kan.id)
        add(EntryKind.expense, d(9, 14), 5_200, "食費", "鍋の材料", go.id)
        add(EntryKind.expense, d(9, 18), 8_700, "電気", "", go.id)
        add(EntryKind.expense, d(9, 19), 5_500, "ネット", "", kan.id)
        add(EntryKind.income, d(9, 20), -2_400, None, "楽天ポイント還元", kan.id)
        # ガス 和 水道 故意不填：面板要显示成灰色参考值，不是预填的真值

        total = len(s.exec(select(Entry)).all())
        print(f"建好 {len(PEOPLE)} 个成员（密码 {PASSWORD}）、2 张出过的账单、{total} 笔账")
        print("  7 月那张已结清；8 月那张只转了一笔；当前草稿的 ガス / 水道 空着")


def finish_cut(s: Session, actor_id: int, label: str, at: dt.datetime):
    """出账，然后把出账时刻改成想要的那天 —— 种子要铺出一条像样的时间线。"""
    st = cut_statement(s, actor_id=actor_id, label=label)
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
