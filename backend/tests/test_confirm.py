"""「确认已完成」不许重复记账（2026-09 审计 integrity-1，critical）。

转出方和转入方各点一次、或者「确定」被连点两下，原来都会记成两笔转账 ——
后端一句不查。现在走 /api/bill/confirm：带上「打开对话框时看到还差多少」，
对不上就 409。
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.models import Member

SEP = dt.date(2026, 9, 10).isoformat()


def _plan(client: TestClient, auth) -> list[dict]:
    return client.get("/api/bill", headers=auth).json()["transfers"]


def _setup(client: TestClient, auth, members: list[Member]) -> dict:
    a = members[0]
    r = client.post(
        "/api/entries", headers=auth,
        json={"kind": "expense", "date": SEP, "amount_jpy": 30_000, "payer_id": a.id},
    )
    assert r.status_code == 201, r.text
    plan = _plan(client, auth)
    assert plan, "三个人均摊 A 垫的 30,000，该有两笔转账"
    return plan[0]


def test_second_confirm_with_the_same_view_is_refused(client: TestClient, auth, members) -> None:
    tr = _setup(client, auth, members)
    body = {"from_id": tr["from_id"], "to_id": tr["to_id"], "amount": tr["amount"], "expect_left": tr["amount"]}
    first = client.post("/api/bill/confirm", json=body, headers=auth)
    assert first.status_code == 201, first.text
    assert first.json()["kind"] == "settlement"

    again = client.post("/api/bill/confirm", json=body, headers=auth)
    assert again.status_code == 409
    assert again.json()["code"] == "transfer_changed"
    assert again.json()["detail"]["left"] == 0

    settlements = [
        e for e in client.get("/api/entries", headers=auth).json() if e["kind"] == "settlement"
    ]
    assert len(settlements) == 1


def test_partial_payment_then_fresh_view_still_works(client: TestClient, auth, members) -> None:
    """部分还款之后，拿着新看到的「还差多少」照样能再记一笔。"""
    tr = _setup(client, auth, members)
    part = {"from_id": tr["from_id"], "to_id": tr["to_id"], "amount": 4_000, "expect_left": tr["amount"]}
    assert client.post("/api/bill/confirm", json=part, headers=auth).status_code == 201

    # 还拿着旧的数（另一台设备没刷新）：不记，告诉它现在是多少
    stale = client.post("/api/bill/confirm", json={**part, "amount": tr["amount"]}, headers=auth)
    assert stale.status_code == 409
    left = stale.json()["detail"]["left"]
    assert left == tr["amount"] - 4_000

    rest = {**part, "amount": left, "expect_left": left}
    assert client.post("/api/bill/confirm", json=rest, headers=auth).status_code == 201
    assert _plan(client, auth) == [p for p in _plan(client, auth)]  # 仍能正常出账单页


def test_pair_not_in_plan_has_nothing_left(client: TestClient, auth, members) -> None:
    tr = _setup(client, auth, members)
    body = {"from_id": tr["to_id"], "to_id": tr["from_id"], "amount": 1_000, "expect_left": 1_000}
    r = client.post("/api/bill/confirm", json=body, headers=auth)
    assert r.status_code == 409
    assert r.json()["detail"]["left"] == 0


def test_same_client_key_records_only_once(client: TestClient, auth, members) -> None:
    """离线草稿补交：请求其实到过后端、只是响应丢了 —— 带同一个键再来，不许记第二笔。"""
    a = members[0]
    body = {"kind": "expense", "date": SEP, "amount_jpy": 1_200, "payer_id": a.id,
            "client_key": "k-0123456789abcdef"}
    first = client.post("/api/entries", json=body, headers=auth)
    again = client.post("/api/entries", json=body, headers=auth)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert len([e for e in client.get("/api/entries", headers=auth).json() if e["amount_jpy"] == 1_200]) == 1
