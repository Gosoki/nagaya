from __future__ import annotations

import datetime as dt

from sqlmodel import Session

from tests.test_api import *  # noqa: F401,F403
from app.models import Category


def test_repro(client, auth, members, session: Session):
    a, *_ = members
    cat = Category(name="水道", icon="water_drop", color="#29b6f6", monthly=True, display_order=0)
    session.add(cat)
    session.commit()
    session.refresh(cat)

    r = client.post("/api/entries", headers=auth, json={
        "kind": "expense", "date": "2026-09-10", "amount_jpy": 12000,
        "payer_id": a.id, "category_id": cat.id, "title": "7〜8月分",
        "period_start": "2026-07-01", "period_end": "2026-08-31",
    })
    assert r.status_code in (200, 201), r.text
    pid = r.json()["period_id"]

    m = client.get(f"/api/periods/{pid}/monthly", headers=auth).json()
    row = [x for x in m["rows"] if x["category_id"] == cat.id][0]
    print("ROW:", row["name"], row["entry_id"], row["amount"], row["version"])

    bill = client.get(f"/api/periods/{pid}/bill", headers=auth).json()
    print("COVERS BEFORE:", bill["covers"])

    # 前端 MonthlyFixed.save() 的 PATCH，原样照抄
    r2 = client.patch(
        f"/api/entries/{row['entry_id']}?version={row['version']}",
        headers=auth,
        json={
            "kind": "expense",
            "date": row["date"] or m["default_date"],
            "amount_jpy": 12500,
            "payer_id": a.id,
            "category_id": row["category_id"],
            "title": row["name"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "rule": None,
        },
    )
    print("PATCH:", r2.status_code, r2.text[:200])
    after = client.get(f"/api/entries/{row['entry_id']}", headers=auth)
    print("GET entry:", after.status_code, after.text[:300])
    bill2 = client.get(f"/api/periods/{pid}/bill", headers=auth).json()
    print("COVERS AFTER:", bill2["covers"])
