"""2026-09 审计里安全那一组的回归。每条都对应一次实地复现过的问题。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.rules import RuleError, expand
from app.models import Member


def test_login_is_throttled_after_repeated_failures(client: TestClient, auth, members) -> None:
    """原来登录不限次数：局域网里一秒能试几十个密码。前 5 次随便错，之后要等。"""
    for _ in range(5):
        r = client.post("/api/auth/login", json={"name": "a", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"name": "a", "password": "wrong"})
    assert r.status_code == 429
    assert r.json()["code"] == "too_many_logins"
    assert r.json()["detail"]["seconds"] > 0
    # 等待期间连对的密码也不验 —— 否则攻击者照样拿到了「这次对不对」
    r = client.post("/api/auth/login", json={"name": "a", "password": "pw123456"})
    assert r.status_code == 429


def test_throttle_is_per_name_so_nobody_can_lock_out_a_roommate(client: TestClient, auth) -> None:
    """按「这台机器 + 这个登录名」记：对着 b 乱试，不影响 a 登录。"""
    for _ in range(8):
        client.post("/api/auth/login", json={"name": "b", "password": "wrong"})
    r = client.post("/api/auth/login", json={"name": "a", "password": "pw123456"})
    assert r.status_code == 200


def test_success_resets_the_counter(client: TestClient, auth) -> None:
    for _ in range(4):
        client.post("/api/auth/login", json={"name": "a", "password": "wrong"})
    assert client.post("/api/auth/login", json={"name": "a", "password": "pw123456"}).status_code == 200
    for _ in range(5):
        assert client.post("/api/auth/login", json={"name": "a", "password": "wrong"}).status_code == 401


def test_password_minimum_length(client: TestClient, auth, members: list[Member]) -> None:
    """前端改密码那一格要 6 位，后端原来不管 —— 绕过界面就能设成一位数。"""
    r = client.patch(
        f"/api/members/{members[0].id}", json={"password": "123", "old_password": "pw123456"}, headers=auth
    )
    assert r.status_code == 400
    assert r.json()["code"] == "password_too_short"
    r = client.post("/api/members", json={"name": "d", "password": "12"}, headers=auth)
    assert r.json()["code"] == "password_too_short"


def test_oversized_body_is_rejected_before_auth(client: TestClient) -> None:
    """请求体原来没有上限，未登录就能 POST 几个 G 把进程撑满。"""
    r = client.post(
        "/api/entries", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"


def test_backup_path_cannot_point_into_the_web_root(client: TestClient, auth) -> None:
    """备份是整本账的明文（含密码哈希）。指进前端产物目录，未登录就能下载。"""
    web = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "pwa"
    r = client.put("/api/settings/backup_path", json={"value": str(web)}, headers=auth)
    assert r.status_code == 400
    assert r.json()["code"] == "setting_invalid"
    r = client.put("/api/settings/backup_path", json={"value": "a\x00b"}, headers=auth)
    assert r.status_code == 400


def test_database_files_are_never_served_as_static() -> None:
    """就算有 .db 落进了前端目录，也不许从静态回退里发出去。"""
    from app.main import app
    from app.spa import DIST

    if not DIST.is_dir():
        pytest.skip("前端还没打包")
    r = TestClient(app).get("/nagaya-20260101-000000.db")
    assert r.status_code == 404


def test_unknown_remainder_rule_is_rejected_up_front() -> None:
    """原来要等到哪天真有除不尽的 1 円才报错。"""
    with pytest.raises(RuleError):
        expand({"mode": "equal", "remainder_to": "nobody"}, [1, 2, 3])


def test_display_order_is_bounded(client: TestClient, auth) -> None:
    """2^63-1 的排序号会让之后「新建」溢出，翻成一个误导人的 404。"""
    r = client.post("/api/memos", json={"title": "x", "display_order": 2**63 - 1}, headers=auth)
    assert r.status_code == 422


def test_config_changes_are_audited(client: TestClient, auth, members, session) -> None:
    """成员、分类、设置的改动也留痕（审计 integrity-6）；密码哈希和头像不进日志。"""
    from sqlmodel import select

    from app.models import AuditLog

    a = members[0]
    client.patch(f"/api/members/{members[1].id}", json={"display_name": "B2"}, headers=auth)
    r = client.post("/api/categories", json={"name": "网费", "monthly": True}, headers=auth)
    client.patch(f"/api/categories/{r.json()['id']}", json={"same_as_last": True}, headers=auth)
    client.put("/api/settings/remainder_to", json={"value": "order"}, headers=auth)
    # 改密码放最后：一改旧 token 就作废了
    client.patch(f"/api/members/{a.id}", json={"password": "newpass1", "old_password": "pw123456"}, headers=auth)

    logs = list(session.exec(select(AuditLog).where(AuditLog.target_table != "entry")))
    tables = [(x.target_table, x.action) for x in logs]
    assert ("member", "update") in tables
    assert ("member", "password") in tables
    assert ("category", "create") in tables and ("category", "update") in tables
    assert ("setting", "update") in tables
    for x in logs:
        blob = str(x.before_json) + str(x.after_json)
        assert "password_hash" not in blob and "avatar'" not in blob


def test_chunked_oversized_body_is_413_too(client: TestClient) -> None:
    """没有 Content-Length 的分块上传，超限时原来回的是 400「解析请求体出错」。"""

    def chunks():
        for _ in range(3):
            yield b"x" * (512 * 1024)

    r = client.post("/api/entries", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"


def test_login_throttle_holds_under_concurrency(client: TestClient, auth) -> None:
    """并发发一批错密码，原来先查后记，一批全部真的去验了密码。"""
    from concurrent.futures import ThreadPoolExecutor

    def attempt(_):
        return client.post("/api/auth/login", json={"name": "a", "password": "wrong"}).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(attempt, range(24)))
    assert codes.count(401) <= 5
    assert codes.count(429) >= 19


def test_confirm_amount_rejects_bool(client: TestClient, auth, members) -> None:
    r = client.post(
        "/api/bill/confirm",
        json={"from_id": members[1].id, "to_id": members[0].id, "amount": True, "expect_left": 0},
        headers=auth,
    )
    assert r.status_code == 422


def test_tilde_user_backup_path_is_400_not_500(client: TestClient, auth) -> None:
    r = client.put("/api/settings/backup_path", json={"value": "~nosuchuser_zz/backups"}, headers=auth)
    assert r.status_code == 400
