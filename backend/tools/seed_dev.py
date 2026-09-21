"""开发用种子数据：三个室友 + 几笔账。

    .venv/bin/python -m tools.seed_dev

密码统一 dev12345。**只在开发库上跑**，真用起来之前要删掉这些账号。
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.auth import hash_password
from app.db import engine
from app.init_db import init_db
from app.models import Category, EntryKind, Member
from app.services import settings as settings_svc
from app.services.ledger import create_entry

PEOPLE = [("go", "Go", "#3d4785"), ("kan", "Kan", "#26a69a"), ("zen", "Zen", "#ef6c00")]
PASSWORD = "dev12345"


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
                joined_on=dt.date(2026, 4, 1), password_hash=hash_password(PASSWORD),
            )
            s.add(m)
            members.append(m)
        s.commit()
        for m in members:
            s.refresh(m)

        go, kan, zen = members
        settings_svc.set_(s, "default_payer_id", go.id)

        cats = {c.name: c for c in s.exec(select(Category))}
        rent = cats["家賃"]
        # 家賃走固定金额（D12：房间大小不同，不是比例）
        rent.default_rule_json = {
            "mode": "exact",
            "exact": {str(go.id): 45_000, str(kan.id): 40_000, str(zen.id): 35_000},
        }
        s.add(rent)
        s.commit()

        today = dt.date.today()
        rows = [
            (EntryKind.expense, today.replace(day=1), 120_000, "家賃", "家賃", go.id),
            (EntryKind.expense, today, 8_700, "電気", "", go.id),
            (EntryKind.expense, today, 4_200, "ガス", "", go.id),
            (EntryKind.expense, today, 12_000, "水道", "7〜8月分", go.id),
            (EntryKind.expense, today, 5_500, "ネット", "", kan.id),
            (EntryKind.expense, today, 1_380, "日用品", "トイレットペーパー", zen.id),
            (EntryKind.income, today, -3_000, "その他", "電気代キャッシュバック", go.id),
        ]
        for kind, on, amount, cat_name, title, payer in rows:
            cat = cats[cat_name]
            create_entry(
                s, actor_id=go.id, kind=kind, on=on, amount=amount, payer_id=payer,
                category_id=cat.id, category_rule=cat.default_rule_json, title=title,
                period_start=dt.date(2026, 7, 1) if cat_name == "水道" else None,
                period_end=dt.date(2026, 8, 31) if cat_name == "水道" else None,
            )

        print(f"建好 {len(PEOPLE)} 个成员（密码 {PASSWORD}）和 {len(rows)} 笔账")


if __name__ == "__main__":
    main()
