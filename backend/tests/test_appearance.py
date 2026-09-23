"""App 名字和图标（appearance 路由）。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_app_name_and_icon_can_be_changed(client: TestClient, auth) -> None:
    """这屋自己的 App 名字和图标。

    自托管、一户一个实例，加到主屏之后图标和名字就是「这是哪个屋的账本」的
    全部标识 —— 默认那个红屋顶对别人不合适，而改它本来要改代码重新打包。
    """
    import io

    from PIL import Image

    # 没设过的时候：清单用打包时那套图标
    m = client.get("/api/appearance/manifest.webmanifest").json()
    assert m["name"] == "長屋 nagaya"
    assert all(i["src"].startswith("/icons/") for i in m["icons"])
    assert client.get("/api/appearance/icon/192.png").status_code == 404

    # 改名字走的是普通设置那条路（于是备份、校验全是白拿的）
    assert client.put("/api/settings/app_name", headers=auth, json={"value": "三丁目"}).status_code == 200
    assert client.get("/api/appearance/manifest.webmanifest").json()["name"] == "三丁目"

    # 传图标：任意尺寸进来，出去是方的
    buf = io.BytesIO()
    Image.new("RGB", (640, 400), (200, 30, 30)).save(buf, "PNG")
    r = client.post("/api/appearance/icon", headers=auth,
                    files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    version = r.json()["version"]
    assert version > 0

    for size in (32, 180, 192, 512):
        got = client.get(f"/api/appearance/icon/{size}.png")
        assert got.status_code == 200, size
        img = Image.open(io.BytesIO(got.content))
        assert img.size == (size, size)
    # 尺寸不开放任意值 —— 免得有人拿 /icon/99999.png 让服务器去画一张大图
    assert client.get("/api/appearance/icon/99999.png").status_code == 404

    m = client.get("/api/appearance/manifest.webmanifest").json()
    assert all("/api/appearance/icon/" in i["src"] for i in m["icons"])
    assert all(f"v={version}" in i["src"] for i in m["icons"]), "地址里得带版本号，否则手机永远用死缓存那张"

    # 不是图片的当场拒掉，别存进库
    bad = client.post("/api/appearance/icon", headers=auth,
                      files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400 and bad.json()["code"] == "icon_not_image"

    # 撤回默认
    assert client.delete("/api/appearance/icon", headers=auth).json()["version"] == 0
    # 再传一张：版本号不许和第一张撞（撞了的话地址一样，手机拿着缓存的旧图不放）
    again = client.post("/api/appearance/icon", headers=auth,
                        files={"file": ("logo.png", buf.getvalue(), "image/png")}).json()["version"]
    assert again != version and again > 0
    assert client.delete("/api/appearance/icon", headers=auth).json()["version"] == 0
    assert client.get("/api/appearance/icon/192.png").status_code == 404
    assert all(i["src"].startswith("/icons/") for i in
               client.get("/api/appearance/manifest.webmanifest").json()["icons"])


def test_the_icon_endpoints_do_not_need_a_login(client: TestClient, auth) -> None:
    """图标和清单**不能要登录**：装到主屏那一下是浏览器/系统自己去取的，
    带不上我们的 Authorization 头。图标不是秘密（登录页上本来就印着），
    但账本数据一个字都不从这儿出去。
    """
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 0, 0)).save(buf, "PNG")
    client.post("/api/appearance/icon", headers=auth,
                files={"file": ("l.png", buf.getvalue(), "image/png")})
    assert client.get("/api/appearance/icon/192.png").status_code == 200
    assert client.get("/api/appearance/manifest.webmanifest").status_code == 200
    # 反过来：改名字必须登录
    assert client.put("/api/settings/app_name", json={"value": "x"}).status_code == 401
    assert client.post("/api/appearance/icon", files={"file": ("l.png", b"x", "image/png")}).status_code == 401
