"""HTTP 层回归：认证、错误码、乐观锁、成员 / 头像 / 偏好接口。"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.auth import hash_password

SEP = "2026-09-10"


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
    # version 的起点是随机的（models.Entry.version）：只认「是个正整数」，之后每改一次 +1
    assert isinstance(body["version"], int) and 1 <= body["version"] < 2**31


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
    assert ok.status_code == 200 and ok.json()["version"] == created["version"] + 1

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

    client.post(f"/api/entries/{e['id']}/restore", headers=auth)
    assert len(client.get("/api/entries", headers=auth).json()) == 1


def test_settings_carry_notes_and_validate(client, auth):
    rows = {s["key"]: s for s in client.get("/api/settings", headers=auth).json()}
    assert rows["remainder_to"]["value"] == "payer"
    assert rows["remainder_to"]["note_zh"] and rows["remainder_to"]["note_ja"]
    assert "period_start_day" not in rows, "账期起算日应当随账期机制一起消失"
    assert "settle_due_day" not in rows, "结算日提醒撤了，这一项该跟着消失"

    # 整数项的取值范围要真的拦得住
    assert client.put("/api/settings/monthly_gap_days", headers=auth, json={"value": 25}).status_code == 200
    assert client.put("/api/settings/monthly_gap_days", headers=auth, json={"value": 400}).status_code == 400
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


def test_bad_ids_are_400_not_500(client, auth, members) -> None:
    """引用到不存在的成员/分类，要给结构化的 400，不能撞穿到外键约束上变成 500。

    500 对客户端是「服务器坏了」：既看不出是哪个字段，也不知道该不该重试。
    """
    base = {"kind": "expense", "date": "2026-09-10", "amount_jpy": 1000}
    assert client.post("/api/entries", headers=auth, json={**base, "payer_id": 9999}).status_code == 400
    r = client.post("/api/entries", headers=auth, json={**base, "payer_id": 1, "category_id": 9999})
    assert r.status_code == 400 and r.json()["code"] == "unknown_category"


def test_password_is_yours_alone(client, auth, members) -> None:
    """密码只能自己改 —— 「互相信任」不等于「谁都能把别人锁在门外」。"""
    me, other, *_ = members
    assert client.patch(f"/api/members/{other.id}", headers=auth,
                        json={"password": "hijacked"}).status_code == 403
    # 改自己的也得先报出旧密码 —— 手机搁桌上没锁屏，别人顺手就能改掉
    assert client.patch(f"/api/members/{me.id}", headers=auth,
                        json={"password": "my-own-new-one"}).status_code == 403
    assert client.patch(f"/api/members/{me.id}", headers=auth,
                        json={"password": "my-own-new-one", "old_password": "wrong"}).status_code == 403
    assert client.patch(f"/api/members/{me.id}", headers=auth,
                        json={"password": "my-own-new-one", "old_password": "pw123456"}).status_code == 200
    # 新密码真的生效了
    assert client.post("/api/auth/login", json={"name": me.name, "password": "my-own-new-one"}).status_code == 200


def test_left_on_can_be_cleared(client, auth, members) -> None:
    """退出日填错了要能清掉，不然那个人永远回不来。"""
    me, *_ = members
    assert client.patch(f"/api/members/{me.id}", headers=auth,
                        json={"left_on": "2026-08-31"}).json()["left_on"] == "2026-08-31"
    assert client.patch(f"/api/members/{me.id}", headers=auth,
                        json={"left_on": None}).json()["left_on"] is None


def test_renaming_to_a_taken_name_is_409_like_create(client, auth, members) -> None:
    me, other, *_ = members
    r = client.patch(f"/api/members/{me.id}", headers=auth, json={"name": other.name})
    assert r.status_code == 409, "重名在 POST 那边是 409，PATCH 不该是 500"


def test_login_name_and_password_are_self_only(client, auth, members) -> None:
    """**没法自己恢复的动作只能自己做。**

    密码本来就挡了，理由写得明明白白「改掉别人的密码是一个没法自己恢复的动作」——
    改掉别人的**登录名**是同一件事：实测把 a 的 name 改掉之后，
    他用自己的用户名登录直接 401，而且毫无自救手段。
    """
    _, other, *_ = members
    for patch in ({"name": "hacked"}, {"password": "whatever123"}):
        r = client.patch(f"/api/members/{other.id}", headers=auth, json=patch)
        assert r.status_code == 403, f"{patch} 不该被放行"
    # 这几样**故意**放开：搬出日是家务动作不是自助动作（人搬走了就不开这个 app 了，
    # 只许本人改的话谁也标不掉他，往后每笔账都照样算他一份）；
    # 昵称和颜色改错了当事人自己看得见、也改得回来
    for patch in ({"display_name": "小二"}, {"left_on": "2026-01-01"}, {"left_on": None}):
        assert client.patch(f"/api/members/{other.id}", headers=auth,
                            json=patch).status_code == 200, patch


def test_a_member_without_a_password_cannot_be_created(client, auth) -> None:
    """不给密码建出来的账号**永远登不进来**：密码只能自己改，而他登不进来就改不了，
    别人替他改会被上一条挡下 —— 谁也解不开。"""
    assert client.post("/api/members", headers=auth,
                       json={"name": "ghost"}).status_code == 400


def test_a_broken_default_rule_is_rejected_on_the_spot(client, auth, members) -> None:
    """兜底分摊规则要**当场试着用一下**再存。

    写坏了不会在设置这里报错，而是等到下一次「记一笔」才 500 —— 那时人正在记账，
    完全看不出跟设置有关，而且这一项一坏，谁都记不了账。
    """
    bad = client.put("/api/settings/default_rule", headers=auth,
                     json={"value": {"mode": "ratio", "weights": {"9999": 1}}})
    assert bad.status_code == 400, "点名了不存在的成员，存进去就没人记得了账"
    assert client.put("/api/settings/default_rule", headers=auth,
                      json={"value": "不是对象"}).status_code == 400
    assert client.put("/api/settings/default_rule", headers=auth,
                      json={"value": {"mode": "ratio", "equal_weight": 1}}).status_code == 200

    # 设置没被写坏，记账照常
    ok = client.post("/api/entries", headers=auth,
                     json={"kind": "expense", "date": "2026-09-10", "amount_jpy": 900, "payer_id": 1})
    assert ok.status_code == 201


def test_memos_crud(client, auth) -> None:
    """自己加的备忘：能加、能改、能删。"""
    assert client.get("/api/memos", headers=auth).json() == []
    assert client.post("/api/memos", headers=auth, json={"title": "  "}).status_code == 400

    a = client.post("/api/memos", headers=auth,
                    json={"title": " 垃圾袋 ", "body": "买大号的，超市 B1"}).json()
    assert a["title"] == "垃圾袋", "名字两边的空格要削掉"
    b = client.post("/api/memos", headers=auth, json={"title": "钥匙"}).json()
    assert b["display_order"] > a["display_order"], "新的排在最后，不插队"

    upd = client.patch(f"/api/memos/{a['id']}", headers=auth, json={"body": "改成买中号"}).json()
    assert upd["body"] == "改成买中号" and upd["title"] == "垃圾袋"
    assert client.patch(f"/api/memos/{a['id']}", headers=auth, json={"title": ""}).status_code == 400

    assert client.delete(f"/api/memos/{b['id']}", headers=auth).status_code == 204
    assert [m["id"] for m in client.get("/api/memos", headers=auth).json()] == [a["id"]]
    assert client.delete(f"/api/memos/{b['id']}", headers=auth).status_code == 404


def test_category_note_is_a_standing_memo(client, auth) -> None:
    """固定费那几项的备忘写在分类上 —— 「水费隔月收」每期都成立，
    写进某一笔账的备注里，下个月就找不着了。"""
    cat = client.post("/api/categories", headers=auth,
                      json={"name": "水费", "monthly": True}).json()
    assert cat["note"] == ""
    updated = client.patch(f"/api/categories/{cat['id']}", headers=auth,
                           json={"note": "隔月收：6 / 8 / 10 月"}).json()
    assert updated["note"] == "隔月收：6 / 8 / 10 月"
    assert updated["name"] == "水费", "只发了 note，别的字段不许动"


def _photo(width: int = 2400, height: int = 1600) -> bytes:
    """一张「手机拍的」大图：横着的、带 EXIF 里的方向、几百 KB 起。"""
    from PIL import Image

    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(0, width, 7):          # 画点花纹，纯色压完只有几百字节，测不出东西
            px[x, y] = ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_avatar_upload_compresses_hard(client, auth, members) -> None:
    """前端会先缩小再传，但后端不信它：大图照样压成几 KB 的小方图。"""
    me, *_ = members
    raw = _photo(1200, 800)
    assert len(raw) > 200_000, "测试素材本身要够大，不然压缩比没意义"

    r = client.post(f"/api/members/{me.id}/avatar", headers=auth,
                    files={"file": ("photo.jpg", raw, "image/jpeg")})
    assert r.status_code == 200
    out = r.json()
    assert out["avatar"].startswith(f"/api/members/{me.id}/avatar?v=1-"), "列表里只带地址，地址里带版本号"
    assert len(out["avatar"].rsplit("-", 1)[1]) == 8, "还带着内容指纹：恢复备份把版本号退回去也不会撞上旧地址"
    assert out["avatar_version"] == 1

    got = client.get(out["avatar"], headers=auth)
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/webp"
    assert "immutable" in got.headers["cache-control"], "地址带版本号，图可以长缓存"
    stored = got.content
    assert len(stored) < 30_000, f"压完还有 {len(stored)} 字节，太大了"
    assert len(stored) < len(raw) / 20, "至少要小一个数量级"

    from PIL import Image
    img = Image.open(io.BytesIO(stored))
    assert img.size == (192, 192), "头像是个圆，必须裁成正方形，不能压扁"
    assert img.format == "WEBP"

    listed = {m["id"]: m for m in client.get("/api/members", headers=auth).json()}
    assert listed[me.id]["avatar"] == out["avatar"]
    assert "base64" not in client.get("/api/members", headers=auth).text, "图不跟着成员列表走"


def test_avatar_image_needs_login(client, auth, members) -> None:
    me, other, *_ = members
    client.post(f"/api/members/{me.id}/avatar", headers=auth,
                files={"file": ("photo.jpg", _photo(60, 60), "image/jpeg")})
    assert client.get(f"/api/members/{me.id}/avatar?v=1").status_code == 401
    # 没设过头像的人：404，前端退回色圆
    assert client.get(f"/api/members/{other.id}/avatar?v=0", headers=auth).status_code == 404


def test_avatar_rules(client, auth, members) -> None:
    me, other, *_ = members
    # 超过 1MB 直接拒（前端缩完只有十几 KB，这道闸是给 curl 和旧页面的）
    big = b"\xff\xd8\xff" + b"0" * (1 * 1024 * 1024)
    assert client.post(f"/api/members/{me.id}/avatar", headers=auth,
                       files={"file": ("big.jpg", big, "image/jpeg")}).status_code == 413
    # 不是图片的，给 400 说清楚，别撞成 500
    assert client.post(f"/api/members/{me.id}/avatar", headers=auth,
                       files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400
    # 只能换自己的
    assert client.post(f"/api/members/{other.id}/avatar", headers=auth,
                       files={"file": ("photo.jpg", _photo(60, 60), "image/jpeg")}).status_code == 403


def test_avatar_can_be_removed(client, auth, members) -> None:
    """撤掉头像回到那个色圆 —— 换上去了就撤不下来的话，等于逼着人一直用。"""
    me, *_ = members
    client.post(f"/api/members/{me.id}/avatar", headers=auth,
                files={"file": ("photo.jpg", _photo(300, 300), "image/jpeg")})
    r = client.delete(f"/api/members/{me.id}/avatar", headers=auth)
    assert r.status_code == 200 and r.json()["avatar"] is None
    assert r.json()["avatar_version"] == 2, "版本号要继续往前走，缓存才知道换了"
    assert client.get(f"/api/members/{me.id}/avatar?v=1", headers=auth).status_code == 404


def test_prefs_follow_the_account(client, auth, session, members) -> None:
    """深浅色、主题色存在账号上：谁存的只给谁，换台设备登录还是这一套。"""
    assert client.get("/api/prefs", headers=auth).json() == {}, "没存过就是空的，前端靠它认出「还没对过表」"

    r = client.patch("/api/prefs", headers=auth, json={"scheme": "dark", "theme_color": "rose"})
    assert r.status_code == 200
    assert r.json() == {"scheme": "dark", "theme_color": "rose"}
    r = client.patch("/api/prefs", headers=auth, json={"theme_color": "teal"})
    assert r.json() == {"scheme": "dark", "theme_color": "teal"}, "只改发了的那一项"

    # 另一台设备：重新登录拿一张新 token，读到的是同一份
    again = client.post("/api/auth/login", json={"name": "a", "password": "pw123456"}).json()["token"]
    assert client.get("/api/prefs", headers={"Authorization": f"Bearer {again}"}).json()["theme_color"] == "teal"

    # 室友看不到、也改不到我的
    b = members[1]
    b.password_hash = hash_password("pw123456")
    session.add(b)
    session.commit()
    tb = client.post("/api/auth/login", json={"name": "b", "password": "pw123456"}).json()["token"]
    assert client.get("/api/prefs", headers={"Authorization": f"Bearer {tb}"}).json() == {}

    assert client.get("/api/prefs").status_code == 401


def test_prefs_reject_junk(client, auth) -> None:
    for body in ({"font": "big"}, {"scheme": "<b>"}, {"scheme": "x" * 33}, {"scheme": ""}):
        r = client.patch("/api/prefs", headers=auth, json=body)
        assert r.status_code == 400 and r.json()["code"] == "pref_invalid", body
    assert client.patch("/api/prefs", headers=auth, json={"scheme": 1}).status_code == 422
    assert client.get("/api/prefs", headers=auth).json() == {}, "拒掉的一项都不许落库"


def test_changing_the_password_kills_the_other_sessions(client, auth, members) -> None:
    """手机丢了 / 被人瞄到密码时，改密码是唯一的自救动作 ——
    而它原来不断任何已经发出去的 token（管 90 天）。

    实现上**没有给 Member 加字段**：create_all 不给已有的表补列，加一列就等于
    让老库打不开（实测 `no such column`）。密码哈希本来就随密码变，
    拿它过一道 HMAC 当版本号，schema 一个字节都不用动。
    """
    me, *_ = members
    old_headers = dict(auth)
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    r = client.patch(f"/api/members/{me.id}", headers=old_headers,
                     json={"password": "brandnew123", "old_password": "pw123456"})
    assert r.status_code == 200, r.text

    assert client.get("/api/auth/me", headers=old_headers).status_code == 401, \
        "改完密码，改之前发出去的 token 必须当场失效"
    # 新密码换一张新的就照旧能用 —— 界面上改完密码会自己重登一次
    again = client.post("/api/auth/login", json={"name": me.name, "password": "brandnew123"})
    assert again.status_code == 200
    fresh = {"Authorization": f"Bearer {again.json()['token']}"}
    assert client.get("/api/auth/me", headers=fresh).status_code == 200


def test_housemates_can_add_and_move_people_out(client, auth, members) -> None:
    """成员那一屏走的就是这几条：加人（排最后）、标记搬走、撤销、搬走日不许早于入住日。"""
    me, other, *_ = members
    r = client.post("/api/members", headers=auth, json={
        "name": "dan", "display_name": "Dan", "password": "pw123456", "joined_on": "2026-09-01",
    })
    assert r.status_code == 201, r.text
    dan = r.json()
    assert dan["display_order"] > max(m.display_order for m in members), "新来的排最后，别和排第一的并列"
    assert dan["is_active"] is True

    # 别人也能替他标搬走（搬走的人多半不会再打开这个 app）
    r = client.patch(f"/api/members/{other.id}", headers=auth, json={"left_on": "2026-09-10"})
    assert r.status_code == 200 and r.json()["left_on"] == "2026-09-10"
    r = client.patch(f"/api/members/{other.id}", headers=auth, json={"left_on": None})
    assert r.json()["left_on"] is None, "填错了要能撤回来"

    r = client.patch(f"/api/members/{other.id}", headers=auth, json={"left_on": "2025-12-31"})
    assert r.status_code == 400 and r.json()["code"] == "member_dates_invalid"
    r = client.patch(f"/api/members/{dan['id']}", headers=auth, json={"joined_on": "2026-09-01", "left_on": "2026-09-01"})
    assert r.status_code == 200, "住一天也算"
    listed = {m["id"]: m for m in client.get("/api/members", headers=auth).json()}
    assert listed[other.id]["left_on"] is None, "被拒的那次一个字段都不许落下"


def test_new_members_do_not_all_come_out_the_same_grey(client: TestClient, auth, session) -> None:
    """建人时不给颜色就轮着发一个。

    头像圆点、分摊那条分配条、账单上的每人行，三处全靠这个颜色区分谁是谁 ——
    都留默认灰的话分配条就是一整块灰板，拖完看不出钱挪给了谁。
    而新家建人走的是命令行或接口，没人会先去挑色板。
    """
    from app.models import MEMBER_COLORS

    made = []
    for i in range(3):
        r = client.post("/api/members", headers=auth,
                        json={"name": f"n{i}", "display_name": f"N{i}", "password": "pw123456"})
        assert r.status_code == 201, r.text
        made.append(r.json()["color"])
    assert len(set(made)) == 3, made
    assert all(c in MEMBER_COLORS for c in made), made
    # 自己挑了就用自己的
    r = client.post("/api/members", headers=auth, json={
        "name": "pick", "display_name": "Pick", "password": "pw123456", "color": "#123456",
    })
    assert r.json()["color"] == "#123456"


def test_login_names_are_only_visible_to_their_owner(client, auth, members) -> None:
    """个人设置写着「登录名只有自己看得到」：列表里别人的登录名是空的。"""
    me, other, *_ = members
    listed = {m["id"]: m for m in client.get("/api/members", headers=auth).json()}
    assert listed[me.id]["name"] == "a"
    assert listed[other.id]["name"] == "", "别人的登录名（凭据的一半）不许发出去"
    r = client.patch(f"/api/members/{other.id}", headers=auth, json={"left_on": "2026-12-31"})
    assert r.json()["name"] == ""


def test_patch_entry_rejects_bad_refs_and_rules_with_400(client, auth, session, members) -> None:
    """同样的坏输入，POST 是 400、PATCH 原来是裸 500。"""
    me, *_ = members
    e = client.post("/api/entries", headers=auth, json={
        "date": "2026-09-01", "amount_jpy": 3000, "payer_id": me.id,
    }).json()
    for body in ({"category_id": 99999}, {"rule": {"weights": "abc"}}, {"rule": {"weights": {"x": 1}}},
                 {"rule": {"mode": "exact", "exact": {"1.5": 3000}}}):
        r = client.patch(f"/api/entries/{e['id']}?version={e['version']}", headers=auth, json=body)
        assert r.status_code == 400, (body, r.status_code, r.text[:200])
        # 测试里所有请求共用一个 session：线上每个请求自己的 session 出错就整个回滚
        session.rollback()


def test_restoring_an_entry_that_is_not_deleted_changes_nothing(client, auth, members) -> None:
    me, *_ = members
    e = client.post("/api/entries", headers=auth, json={
        "date": "2026-09-01", "amount_jpy": 3000, "payer_id": me.id,
    }).json()
    r = client.post(f"/api/entries/{e['id']}/restore", headers=auth)
    assert r.status_code == 200 and r.json()["version"] == e["version"], "没删过就什么都别动"


def test_login_input_is_bounded(client, members) -> None:
    r = client.post("/api/auth/login", json={"name": "x" * 1_000_000, "password": "p"})
    assert r.status_code == 422, "超长的名字在进节流表之前就挡掉"



def test_pref_values_with_a_trailing_newline_are_rejected(client, auth) -> None:
    r = client.patch("/api/prefs", headers=auth, json={"scheme": "dark\n"})
    assert r.status_code == 400


# ------------------------------------------------ 固定费量级闸（#4）


def _fixed_cost(session, name: str = "電気"):
    from app.models import Category

    cat = Category(name=name, monthly=True)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    return cat


def _post(client, auth, payer_id: int, category_id: int, amount: int, **extra):
    return client.post("/api/entries", headers=auth, json={
        "kind": "expense", "date": SEP, "amount_jpy": amount, "payer_id": payer_id,
        "category_id": category_id, **extra,
    })


def test_a_fixed_cost_far_off_last_period_asks_before_saving(client, auth, session, members) -> None:
    """多打一个 0、少打一个 0：固定费面板离开输入框就保存，记进去和填对了一模一样。
    先问一句（409 amount_jump），人点了确定带 confirm_jump 再来。两个方向都问。"""
    from app.services.bill import cut_statement, unbilled

    a = members[0]
    elec = _fixed_cost(session)
    assert _post(client, auth, a.id, elec.id, 8_700).status_code == 201, "没出过账的项没东西可比，不问"
    cut_statement(session, actor_id=a.id)

    r = _post(client, auth, a.id, elec.id, 87_000)
    assert r.status_code == 409 and r.json()["code"] == "amount_jump", r.text
    assert r.json()["detail"] == {"ratio": 10, "direction": "up"}
    r = _post(client, auth, a.id, elec.id, 870)
    assert r.status_code == 409 and r.json()["detail"] == {"ratio": 10, "direction": "down"}
    assert unbilled(session) == [], "问的时候一笔都不许记"

    ok = _post(client, auth, a.id, elec.id, 9_100)
    assert ok.status_code == 201
    entry = ok.json()
    # 改金额也问；只改垫付人（金额没动）不问
    r = client.patch(f"/api/entries/{entry['id']}?version={entry['version']}", headers=auth,
                     json={"amount_jpy": 91_000})
    assert r.status_code == 409 and r.json()["code"] == "amount_jump"
    # 改的时候本期合计不算这一笔的旧金额（exclude_id）。算进去的话 9,100 + 870 = 9,970，
    # 够不着上期 8,700 的四分之一，少打一个 0 被放行；正常改成 30,000（约 3.4 倍）反倒要问
    r = client.patch(f"/api/entries/{entry['id']}?version={entry['version']}", headers=auth,
                     json={"amount_jpy": 870})
    assert r.status_code == 409 and r.json()["code"] == "amount_jump", r.text
    assert r.json()["detail"] == {"ratio": 10, "direction": "down"}
    r = client.patch(f"/api/entries/{entry['id']}?version={entry['version']}", headers=auth,
                     json={"amount_jpy": 30_000})
    assert r.status_code == 200, r.text
    entry = r.json()
    r = client.patch(f"/api/entries/{entry['id']}?version={entry['version']}", headers=auth,
                     json={"amount_jpy": 91_000, "confirm_jump": True})
    assert r.status_code == 200 and r.json()["amount_jpy"] == 91_000
    r = client.patch(f"/api/entries/{entry['id']}?version={r.json()['version']}", headers=auth,
                     json={"payer_id": members[1].id})
    assert r.status_code == 200, "金额没变不是打错数"


def test_the_jump_gate_compares_category_totals_not_single_entries(client, auth, session, members) -> None:
    """上期电费分两笔记（8,700 + 300）：拿其中一笔比，下期正常的 9,000 会被当成 30 倍。
    这一期也是合计：先记了 4,500，再记 4,500 是 9,000，不是 4,500。"""
    import datetime as dt

    from app.models import EntryKind
    from app.services.bill import cut_statement
    from app.services.ledger import create_entry

    a = members[0]
    elec = _fixed_cost(session)
    for amount in (8_700, 300):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 9, 10),
                     amount=amount, payer_id=a.id, category_id=elec.id)
    cut_statement(session, actor_id=a.id)
    assert _post(client, auth, a.id, elec.id, 9_000).status_code == 201
    r = _post(client, auth, a.id, elec.id, 30_000)
    assert r.status_code == 409 and r.json()["detail"]["ratio"] == 4.3   # 39,000 / 9,000


def test_the_jump_gate_leaves_alone_what_it_should(client, auth, session, members) -> None:
    """日常分类、收入不问；改一张旧账单上的固定费跟**它的**上一期比；设置填 0 就整个关掉。"""
    from app.models import Category
    from app.services import settings as settings_svc
    from app.services.bill import cut_statement

    a = members[0]
    elec = _fixed_cost(session)
    daily = Category(name="日用", monthly=False)
    session.add(daily)
    session.commit()
    session.refresh(daily)
    first = _post(client, auth, a.id, elec.id, 8_700).json()
    cut_statement(session, actor_id=a.id)
    second = _post(client, auth, a.id, elec.id, 9_000).json()
    cut_statement(session, actor_id=a.id)

    assert _post(client, auth, a.id, daily.id, 50).status_code == 201
    assert _post(client, auth, a.id, daily.id, 500_000).status_code == 201, "日常支出有自己的离群提示，不在这儿拦"
    r = client.post("/api/entries", headers=auth, json={
        "kind": "income", "date": SEP, "amount_jpy": -870_000, "payer_id": a.id, "category_id": elec.id})
    assert r.status_code == 201, "押金退款这种收入不问"

    # 第一张之前没有电费：改它不问。第二张跟第一张比
    r = client.patch(f"/api/entries/{first['id']}?version={first['version'] + 1}", headers=auth,
                     json={"amount_jpy": 87_000})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/entries/{second['id']}?version={second['version'] + 1}", headers=auth,
                     json={"amount_jpy": 870_000})
    assert r.status_code == 409 and r.json()["detail"]["direction"] == "up"

    settings_svc.set_(session, "fixed_jump_ratio", 0)
    assert _post(client, auth, a.id, elec.id, 870_000).status_code == 201


# ------------------------------------------------ 幂等键撞上一笔已删的账（#43）


def test_replaying_a_key_whose_entry_was_deleted_says_so(client: TestClient, auth, members) -> None:
    """记上过、后来被人删了，草稿又补交一次：原来回 201 和那笔账，前端提示「已记下」，账本里却没有。
    也不许替人再记一笔 —— 那等于把别人刚删的账悄悄记回去。"""
    a = members[0]
    body = {"kind": "expense", "date": SEP, "amount_jpy": 1_200, "payer_id": a.id,
            "client_key": "k-deleted-0123456"}
    first = client.post("/api/entries", json=body, headers=auth).json()
    assert client.delete(f"/api/entries/{first['id']}", headers=auth).status_code == 204

    r = client.post("/api/entries", json=body, headers=auth)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "key_entry_deleted" and r.json()["detail"] == {"entry_id": first["id"]}
    assert client.get("/api/entries", headers=auth).json() == []
    assert set(client.get("/api/balances", headers=auth).json()["balances"].values()) == {0}


# ------------------------------------------------ 固定费 / 日常是定死的（#39）


def test_a_category_cannot_switch_between_fixed_and_daily(client: TestClient, auth, members) -> None:
    """已出的账单上「本期固定费」「含帮买」都按它现分：翻个面，每张旧账单的这两块就跟着变，
    而且不挂「出账后被改过」（钱没动）。界面从来不发这一项，接口也不收。"""
    a, b, _ = members
    cat = client.post("/api/categories", headers=auth, json={"name": "车位", "monthly": True}).json()
    client.post("/api/entries", headers=auth, json={
        "kind": "expense", "date": SEP, "amount_jpy": 8_000, "payer_id": a.id, "category_id": cat["id"],
        "rule": {"mode": "ratio", "weights": {str(b.id): 1}}, "member_ids": [b.id]})
    st = client.post("/api/statements", headers=auth).json()
    before = client.get(f"/api/statements/{st['id']}/bill", headers=auth).json()

    r = client.patch(f"/api/categories/{cat['id']}", headers=auth, json={"monthly": False})
    assert r.status_code == 409 and r.json()["code"] == "monthly_immutable"
    assert client.patch(f"/api/categories/{cat['id']}", headers=auth,
                        json={"monthly": True, "note": "B 的车位"}).status_code == 200, "没变就照常改"
    after = client.get(f"/api/statements/{st['id']}/bill", headers=auth).json()
    assert after["help_total"] == before["help_total"] == 0
    assert after["monthly_ids"] == before["monthly_ids"]


# ------------------------------------------------ 继承的规则点名的人全搬走了（#42）


def test_an_inherited_rule_whose_people_all_left_is_refused_not_spread(
    client: TestClient, auth, session, members
) -> None:
    """分类规则写的「只算 C」，C 搬走之后不带规则记一笔：原来悄悄退回大家均分，
    而前端预览对同一条规则是全 0、不让存 —— 两边口径相反。等价的另一种写法本来就是 400。"""
    import datetime as dt

    a, b, c = members
    for weights in ({str(c.id): 1}, {str(a.id): 0, str(b.id): 0, str(c.id): 1}):
        cat = client.post("/api/categories", headers=auth, json={
            "name": f"C 的东西 {len(weights)}", "default_rule_json": {"mode": "ratio", "weights": weights}}).json()
        c.left_on = dt.date(2026, 9, 1)
        session.add(c)
        session.commit()
        r = client.post("/api/entries", headers=auth, json={
            "kind": "expense", "date": SEP, "amount_jpy": 3_000, "payer_id": a.id, "category_id": cat["id"]})
        assert r.status_code == 400 and r.json()["code"] == "weights_all_zero", (weights, r.text)
        c.left_on = None
        session.add(c)
        session.commit()
    assert client.get("/api/entries", headers=auth).json() == []


# ------------------------------------------------ /api/monthly 每行多出来的字段（契约）


def test_monthly_rows_carry_the_new_fields(client: TestClient, auth, session, members) -> None:
    _fixed_cost(session)
    row = client.get("/api/monthly", headers=auth).json()["rows"][0]
    for key in ("payer_id", "carry_payer_id", "carry_blocked", "carry_blocked_detail",
                "rule_missing_member_ids", "suggest_same_as_last", "maybe_elsewhere",
                "cuts_since_last", "typical_gap"):
        assert key in row, key
    assert row["rule_missing_member_ids"] == [] and row["maybe_elsewhere"] == []
    assert row["suggest_same_as_last"] is False and row["cuts_since_last"] is None


# ------------------------------------------------ 只在前端有的几条校验，后端补上（#57）


def test_member_names_are_trimmed_and_bounded_on_the_server_too(client: TestClient, auth, members) -> None:
    """界面上一直是去空格、不许空、限 20 字再发的；接口原来照单全收：
    65 字的登录名建得出来却永远登不上（登录那边限 64）、「 ren 」登录时打 ren 是 401、
    空昵称让这个人在账单上只剩一个没字的色圆。"""
    me, other, *_ = members
    new = lambda **kw: client.post("/api/members", headers=auth,  # noqa: E731
                                   json={"password": "pw123456", **kw})
    r = new(name="x" * 65)
    assert r.status_code == 400 and r.json()["code"] == "text_too_long"
    r = new(name="ren", display_name="长" * 65)
    assert r.status_code == 400 and r.json()["code"] == "text_too_long"
    for blank in ("", "   "):
        r = new(name="ren", display_name=blank)
        assert r.status_code == 400 and r.json()["code"] == "name_required", repr(blank)

    r = new(name=" ren ", display_name=" Ren ")
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "ren" and r.json()["display_name"] == "Ren"
    assert client.post("/api/auth/login", json={"name": "ren", "password": "pw123456"}).status_code == 200
    assert new(name="x" * 64).status_code == 201, "64 正好是登录那边的上限，收"

    # PATCH 同理，替别人改昵称也一样（昵称不是只许本人改的那几样）
    r = client.patch(f"/api/members/{other.id}", headers=auth, json={"display_name": "  "})
    assert r.status_code == 400 and r.json()["code"] == "name_required"
    r = client.patch(f"/api/members/{me.id}", headers=auth, json={"name": "y" * 65})
    assert r.status_code == 400 and r.json()["code"] == "text_too_long", "改成登不上的名字等于把自己锁在门外"
    r = client.patch(f"/api/members/{me.id}", headers=auth, json={"display_name": " 阿 A "})
    assert r.status_code == 200 and r.json()["display_name"] == "阿 A"


def test_the_fallback_category_must_be_a_daily_one_in_use(client: TestClient, auth, session) -> None:
    """兜底分类指到固定费：日常支出落进固定费，出账时日期被盖、面板上平白多一笔「另有 N 笔」；
    指到归档的：记账那屏连这个分类都看不到。界面的下拉本来就只列日常的，接口照着它卡"""
    from app.models import Category

    rent = Category(name="家賃", monthly=True)
    gone = Category(name="旧的", archived=True)
    daily = Category(name="日用品")
    for c in (rent, gone, daily):
        session.add(c)
    session.commit()
    for c in (rent, gone, daily):
        session.refresh(c)
    for bad in (rent.id, gone.id):
        r = client.put("/api/settings/fallback_category_id", headers=auth, json={"value": bad})
        assert r.status_code == 400 and r.json()["code"] == "setting_invalid", bad
    assert client.put("/api/settings/fallback_category_id", headers=auth,
                      json={"value": daily.id}).status_code == 200
    assert client.put("/api/settings/fallback_category_id", headers=auth,
                      json={"value": None}).status_code == 200


# ------------------------------------------------ 恢复之后旧编辑页不许改到别人那笔（#71）


def test_a_reused_id_does_not_inherit_a_matching_version(client: TestClient, auth, session, members) -> None:
    """恢复备份之后，新账从「备份里最大的 id + 1」重新编号；恢复前就开着的编辑页拿着同一个 id。

    version 原来一律从 1 起，乐观锁对不出来 —— 那台手机一点保存，别人刚记的那笔
    （金额、付款人、分摊）整个被换掉。起点是随机数之后，旧页面上那个 version 对不上。
    这里用「硬删掉最后一笔再记一笔」模拟恢复：SQLite 普通 rowid 表会把同一个 id 发出去。
    """
    from sqlalchemy import text

    me, other, *_ = members
    body = {"date": "2026-09-01", "amount_jpy": 1_111, "payer_id": me.id, "title": "恢复前"}
    stale = client.post("/api/entries", headers=auth, json=body).json()   # 手机上开着它的编辑页
    session.execute(text("delete from entry_share where entry_id = :i"), {"i": stale["id"]})
    session.execute(text("delete from entry where id = :i"), {"i": stale["id"]})
    session.commit()
    fresh = client.post("/api/entries", headers=auth,
                        json={**body, "amount_jpy": 4_444, "payer_id": other.id, "title": "别人刚记的"}).json()
    assert fresh["id"] == stale["id"], "前提：同一个 id 又被发出去了"

    r = client.patch(f"/api/entries/{fresh['id']}?version={stale['version']}", headers=auth,
                     json={"amount_jpy": 1_111, "payer_id": me.id, "title": "手机上改的"})
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    r = client.delete(f"/api/entries/{fresh['id']}?version={stale['version']}", headers=auth)
    assert r.status_code == 409, "删除走的是同一把锁"
    kept = client.get(f"/api/entries/{fresh['id']}", headers=auth).json()
    assert (kept["amount_jpy"], kept["title"]) == (4_444, "别人刚记的")


# ------------------------------------------------ 删除也带乐观锁（#37）


def test_deleting_with_a_stale_version_is_refused(client: TestClient, auth, members) -> None:
    """固定费面板清空一格＝删那一笔，带着它读到的 version。室友刚出完账（version 跟着 +1），
    这边再删的就是刚发进群里那张单子上的账 —— 必须 409，那一笔原样留着。

    PATCH 带 version 早有用例，DELETE 一条都没有：把那道比较拆掉全套照样绿。"""
    me, *_ = members
    e = client.post("/api/entries", headers=auth,
                    json={"date": SEP, "amount_jpy": 120_000, "payer_id": me.id}).json()
    total = lambda: client.get("/api/balances", headers=auth).json()["balances"]  # noqa: E731
    st = client.post("/api/statements", headers=auth).json()["id"]
    now = client.get(f"/api/entries/{e['id']}", headers=auth).json()
    assert now["version"] == e["version"] + 1 and now["statement_id"] == st

    before = total()
    r = client.delete(f"/api/entries/{e['id']}?version={e['version']}", headers=auth)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    assert client.get(f"/api/entries/{e['id']}", headers=auth).status_code == 200
    assert client.get(f"/api/statements/{st}/bill", headers=auth).json()["total_expense"] == 120_000
    assert total() == before

    assert client.delete(f"/api/entries/{e['id']}?version={now['version']}", headers=auth).status_code == 204
    # 已经删掉的再拿旧 version 删一次：什么都不做（重试不该 409，也不该再记一条审计）
    assert client.delete(f"/api/entries/{e['id']}?version={e['version']}", headers=auth).status_code == 204
