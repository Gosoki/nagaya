"""HTTP 层回归：认证、错误码、乐观锁、关账保护。"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import hash_password
from app.db import get_session
from app.main import app
from app.models import Member

SEP = "2026-09-10"


@pytest.fixture
def client(session: Session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)          # 不用 with：避免触发 lifespan 去建真实的库
    app.dependency_overrides.clear()


@pytest.fixture
def auth(client, session, members):
    a = members[0]
    a.password_hash = hash_password("pw123456")
    session.add(a)
    session.commit()
    r = client.post("/api/auth/login", json={"name": "a", "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_rejects_wrong_password(client, session, members):
    a = members[0]
    a.password_hash = hash_password("pw123456")
    session.add(a)
    session.commit()
    assert client.post("/api/auth/login", json={"name": "a", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"name": "zzz", "password": "x"}).status_code == 401


def test_endpoints_require_login(client, members):
    for path in ("/api/members", "/api/entries", "/api/balances", "/api/settings"):
        assert client.get(path).status_code == 401, path


def test_me(client, auth):
    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["name"] == "a" and r.json()["is_active"] is True


def test_create_entry_returns_shares(client, auth, members):
    a, b, c = members
    r = client.post(
        "/api/entries",
        headers=auth,
        json={"kind": "expense", "date": SEP, "amount_jpy": 10_000, "payer_id": a.id, "title": "日用品"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["shares"] == {str(a.id): 3334, str(b.id): 3333, str(c.id): 3333}
    assert sum(body["shares"].values()) == 10_000
    assert body["statement_id"] is None      # 还没出账，在当前草稿里
    assert body["version"] == 1


def test_balances_sum_to_zero_over_http(client, auth, members):
    a, b, _ = members
    client.post("/api/entries", headers=auth,
                json={"kind": "expense", "date": SEP, "amount_jpy": 120_000, "payer_id": a.id})
    client.post("/api/entries", headers=auth,
                json={"kind": "income", "date": SEP, "amount_jpy": -3_000, "payer_id": b.id})
    bal = client.get("/api/balances", headers=auth).json()["balances"]
    assert sum(bal.values()) == 0


def test_bad_sign_returns_structured_error(client, auth, members):
    a, *_ = members
    r = client.post("/api/entries", headers=auth,
                    json={"kind": "expense", "date": SEP, "amount_jpy": -100, "payer_id": a.id})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_sign"


def test_exact_mode_mismatch_tells_the_diff(client, auth, members):
    """前端要靠 detail.diff 红字显示差多少。"""
    a, b, c = members
    r = client.post(
        "/api/entries", headers=auth,
        json={"kind": "expense", "date": SEP, "amount_jpy": 120_000, "payer_id": a.id,
              "rule": {"mode": "exact",
                       "exact": {str(a.id): 45_000, str(b.id): 40_000, str(c.id): 30_000}}},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "sum_mismatch"
    assert r.json()["detail"]["diff"] == 5_000


def test_version_conflict(client, auth, members):
    """两个人同时改同一笔：后提交的被挡下，而不是悄悄覆盖。"""
    a, *_ = members
    created = client.post("/api/entries", headers=auth,
                          json={"kind": "expense", "date": SEP, "amount_jpy": 1_000,
                                "payer_id": a.id}).json()
    ok = client.patch(f"/api/entries/{created['id']}?version={created['version']}", headers=auth,
                      json={"date": SEP, "amount_jpy": 2_000, "payer_id": a.id})
    assert ok.status_code == 200 and ok.json()["version"] == 2

    stale = client.patch(f"/api/entries/{created['id']}?version={created['version']}", headers=auth,
                         json={"date": SEP, "amount_jpy": 3_000, "payer_id": a.id})
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"



def test_soft_delete_and_restore(client, auth, members):
    a, *_ = members
    e = client.post("/api/entries", headers=auth,
                    json={"kind": "expense", "date": SEP, "amount_jpy": 9_000, "payer_id": a.id}).json()
    assert client.delete(f"/api/entries/{e['id']}", headers=auth).status_code == 204
    assert client.get("/api/entries", headers=auth).json() == []
    assert sum(client.get("/api/balances", headers=auth).json()["balances"].values()) == 0
    assert len(client.get("/api/entries?include_deleted=true", headers=auth).json()) == 1

    client.post(f"/api/entries/{e['id']}/restore", headers=auth)
    assert len(client.get("/api/entries", headers=auth).json()) == 1


def test_settings_carry_notes_and_validate(client, auth):
    rows = {s["key"]: s for s in client.get("/api/settings", headers=auth).json()}
    assert rows["remainder_to"]["value"] == "payer"
    assert rows["remainder_to"]["note_zh"] and rows["remainder_to"]["note_ja"]
    assert rows["settle_due_day"]["value"] is None          # 你们还没定，留空
    assert "period_start_day" not in rows, "账期起算日应当随账期机制一起消失"

    assert client.put("/api/settings/settle_due_day", headers=auth, json={"value": 25}).status_code == 200
    assert client.put("/api/settings/settle_due_day", headers=auth, json={"value": 40}).status_code == 400
    assert client.put("/api/settings/remainder_to", headers=auth, json={"value": "nope"}).status_code == 400
    assert client.put("/api/settings/nonexistent", headers=auth, json={"value": 1}).status_code == 404




def test_patch_does_not_touch_fields_you_did_not_send(client, auth, members):
    """**改金额不该顺手换掉垫付人。**

    固定费那一屏只显示金额，压根没有付款人选择器。原来 PATCH 复用 EntryIn
    （payer_id 必填），面板被迫带上「默认垫付人」，于是 Kan 垫的电费被 Go 改一下
    金额就算到了 Go 头上 —— 两人余额各错一个电费钱，界面上零提示。
    """
    a, b, _ = members
    created = client.post("/api/entries", headers=auth,
                          json={"kind": "expense", "date": SEP, "amount_jpy": 8_700,
                                "payer_id": b.id, "title": "電気"}).json()
    assert created["payer_id"] == b.id
    before = client.get("/api/balances", headers=auth).json()["balances"]

    # 只改金额，别的一个字段都不传
    patched = client.patch(f"/api/entries/{created['id']}?version={created['version']}",
                           headers=auth, json={"amount_jpy": 8_750}).json()
    assert patched["payer_id"] == b.id, "垫付人被悄悄换掉了"
    assert patched["title"] == "電気"
    assert patched["amount_jpy"] == 8_750

    after = client.get("/api/balances", headers=auth).json()["balances"]
    assert (after[str(b.id)] - before[str(b.id)]) > 0, "改大金额后垫付人的债权应当变多"
    assert sum(after.values()) == 0
