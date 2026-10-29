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
    # 两次凑够了：此刻的方案里不该再有这一对
    pair = (tr["from_id"], tr["to_id"])
    assert all((p["from_id"], p["to_id"]) != pair for p in _plan(client, auth))


def test_confirm_on_an_issued_bill_is_refused_the_second_time(
    client: TestClient, auth, members
) -> None:
    """在**出过的**账单上点「已完成」：按那张冻结的方案减掉出账后已经转的。
    同一个画面再点一次（另一方也点了、或者连点），不重复记"""
    _setup(client, auth, members)
    st = client.post("/api/statements", headers=auth).json()["id"]
    tr = client.get(f"/api/statements/{st}/bill", headers=auth).json()["transfers"][0]
    body = {"statement_id": st, "from_id": tr["from_id"], "to_id": tr["to_id"],
            "amount": tr["amount"], "expect_left": tr["amount"]}
    assert client.post("/api/bill/confirm", json=body, headers=auth).status_code == 201
    again = client.post("/api/bill/confirm", json=body, headers=auth)
    assert again.status_code == 409
    assert again.json()["detail"]["left"] == 0


def test_pair_not_in_plan_has_nothing_left(client: TestClient, auth, members) -> None:
    tr = _setup(client, auth, members)
    body = {"from_id": tr["to_id"], "to_id": tr["from_id"], "amount": 1_000, "expect_left": 1_000}
    r = client.post("/api/bill/confirm", json=body, headers=auth)
    assert r.status_code == 409
    assert r.json()["detail"]["left"] == 0


def test_an_old_bill_cannot_conjure_debt_once_everyone_is_square(
    client: TestClient, auth, members
) -> None:
    """AUDIT §B.4 原样走一遍：A 垫 30,000 → 出 S1（B→A、C→A 各 10,000）；
    C 垫 60,000 → 出 S2 → 照 S2 全转完。此刻全屋两清，S1 那两行再也不会走钱。

    后端这里是「确认已完成」最后一道闸，两半都要钉住：
      * 「此刻还该转多少」要和实时方案取小 —— 这一对不在实时方案里就是 0；
      * 算出来是 0 就拒收，哪怕手机上带来的 expect_left 也是 0。
    拆掉任意一半，点一下就凭空多出一万块的债（两行都点是 B、C 各 +10,000、A −20,000）。"""
    a, _, c = members
    post = lambda body: client.post("/api/entries", headers=auth, json=body)  # noqa: E731
    assert post({"kind": "expense", "date": SEP, "amount_jpy": 30_000, "payer_id": a.id}).status_code == 201
    s1 = client.post("/api/statements", headers=auth).json()["id"]
    s1_plan = client.get(f"/api/statements/{s1}/bill", headers=auth).json()["transfers"]
    assert sorted(t["amount"] for t in s1_plan) == [10_000, 10_000]

    assert post({"kind": "expense", "date": SEP, "amount_jpy": 60_000, "payer_id": c.id}).status_code == 201
    s2 = client.post("/api/statements", headers=auth).json()["id"]
    for t in client.get(f"/api/statements/{s2}/bill", headers=auth).json()["transfers"]:
        assert post({"kind": "settlement", "date": SEP, "amount_jpy": t["amount"],
                     "payer_id": t["from_id"], "to_member_id": t["to_id"]}).status_code == 201
    assert set(client.get("/api/balances", headers=auth).json()["balances"].values()) == {0}, "前提：全屋两清"
    n = len([e for e in client.get("/api/entries", headers=auth).json() if e["kind"] == "settlement"])

    for t in s1_plan:
        for expect in (t["amount"], 0):
            r = client.post("/api/bill/confirm", headers=auth, json={
                "statement_id": s1, "from_id": t["from_id"], "to_id": t["to_id"],
                "amount": t["amount"], "expect_left": expect,
            })
            assert r.status_code == 409, (t, expect, r.text)
            assert r.json()["code"] == "transfer_changed" and r.json()["detail"]["left"] == 0

    assert set(client.get("/api/balances", headers=auth).json()["balances"].values()) == {0}
    assert len([e for e in client.get("/api/entries", headers=auth).json() if e["kind"] == "settlement"]) == n
