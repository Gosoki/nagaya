"""静态资源与缓存头 —— 用户报的「余额账目点不开」就出在这一层。

链条是这样的：新版发布 → 旧 chunk 被删 → 还开着的旧页面点 Tab 去 import 那个
chunk → 服务端把 index.html 当 JS 返回（200 text/html）→ 浏览器拒绝执行 →
动态 import 抛错 → 路由导航被 reject → **界面上点了没反应，零提示**。

这几条回归了不会有人立刻发现（本地开发一直是新版），所以必须有测试钉着。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import DIST, app

pytestmark = pytest.mark.skipif(not DIST.is_dir(), reason="前端还没打包")


@pytest.fixture
def client():
    return TestClient(app)


def test_index_must_revalidate(client) -> None:
    """index.html 不带缓存头的话，浏览器会按启发式规则（自上次修改起 10%）自作主张缓存。
    产物放一周就有十几个小时完全不问服务器 —— 三个人于是跑着不同版本的记账 app。"""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.headers.get("cache-control") == "no-cache"


def test_hashed_assets_are_immutable(client) -> None:
    """assets/ 下是内容哈希文件名，内容一变文件名就变，可以永久缓存。"""
    name = next(p.name for p in (DIST / "assets").glob("*.js"))
    r = client.get(f"/assets/{name}")
    assert r.status_code == 200
    assert "immutable" in r.headers.get("cache-control", "")


def test_service_worker_must_revalidate(client) -> None:
    """sw.js 被缓存住就再也换不了版了。"""
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_missing_asset_is_404_not_html(client) -> None:
    """**这条是「点不开」的根**。

    不存在的 chunk 必须 404。返回 index.html 的话浏览器会拿到一坨 HTML 去当 JS 执行，
    报的是 MIME 错误，而界面上只表现为「点了没反应」，查起来指不到任何地方。
    """
    r = client.get("/assets/OldPage-deadbeef.js")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")


def test_client_routes_still_fall_back_to_index(client) -> None:
    """无后缀的路径是客户端路由，仍然要回退 —— 否则刷新就白屏。"""
    for path in ("/bill", "/entries", "/monthly", "/login"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "text/html" in r.headers["content-type"], path


def test_unknown_api_paths_stay_404(client) -> None:
    """/api 下的未知路径不能被 index.html 吞掉，否则前端会拿 HTML 去 JSON.parse。"""
    r = client.get("/api/definitely-not-a-thing")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")


def test_head_is_supported(client) -> None:
    """FastAPI 的 @app.get 不像 Starlette 那样自动补 HEAD。
    不注册的话 curl -I 和用 HEAD 探活的监控都会拿到 405，被判成服务挂了。"""
    for path in ("/", "/api/health"):
        assert client.head(path).status_code == 200, path


def test_app_name_with_backslash_keeps_index_alive(client, monkeypatch) -> None:
    """App 名字里带反斜杠，index.html 不许 500。

    `re.sub` 会把**字符串**替换串里的「\\1」「\\d」当反向引用/转义去解析，
    名字叫「a\\1」就是一个 500 —— 所有人连门都进不来，也就没法进设置改回去。"""
    from app import main

    monkeypatch.setattr(
        main.settings_svc, "get", lambda _s, key: "a\\1b\\d" if key == "app_name" else 0
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>a\\1b\\d</title>" in r.text
