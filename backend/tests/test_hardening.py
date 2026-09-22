"""边界输入的回归。

每一条都对应一次**真实探测到的** 500 或静默写坏 —— 起一个临时实例照着打就是这些结果。
这一屏的共同主题：`_check_refs` 的 docstring 写着「不查的话会返回 500，客户端拿到
一句『服务器错误』，既看不出是哪个字段，也不知道能不能重试」。下面每个用例都是
那句话被违反的一处。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.rules import RuleError
from app.models import Category, Entry, EntryKind, Member, Statement
from app.services import ledger
from app.services import bill
from app.services.bill import BillError, cut_statement

TODAY = dt.date(2026, 9, 21)


def _cat(session: Session, name: str = "日用品") -> Category:
    c = Category(name=name, monthly=False)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


# ---------------------------------------------------------------- 金额


def test_absurd_amount_is_refused_not_crashed(session: Session, members) -> None:
    """10**19 原来直接 500（OverflowError: int too large to convert to SQLite INTEGER）。

    而 10**18 更坏 —— 它**存得进去**：全局余额恒等式照样成立，每张账单的合计却
    从此带着这个数，屏幕上没有一处看得出是哪笔账错了。手滑多按几个 0 就是这下场。
    """
    a, *_ = members
    c = _cat(session)
    for bad in (10**19, ledger.MAX_AMOUNT + 1, -(ledger.MAX_AMOUNT + 1)):
        with pytest.raises(ledger.LedgerError) as e:
            ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                                amount=bad, payer_id=a.id, category_id=c.id)
        assert e.value.code == "amount_too_large"

    ok = ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                             amount=ledger.MAX_AMOUNT, payer_id=a.id, category_id=c.id)
    assert ok.amount_jpy == ledger.MAX_AMOUNT       # 上界本身要收


# ---------------------------------------------------------------- 引用


def test_unknown_bundle_is_a_400_not_a_foreign_key_crash(session: Session, members) -> None:
    """bundle 是 _check_refs 唯一漏掉过的外键，乱指一个就撞穿约束返回 500。"""
    a, *_ = members
    c = _cat(session)
    with pytest.raises(ledger.LedgerError) as e:
        ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                            amount=100, payer_id=a.id, category_id=c.id, bundle_id=424242)
    assert e.value.code == "unknown_bundle"


def test_rule_naming_a_stranger_is_a_400_on_patch_too(session: Session, members) -> None:
    """同一个输入走 POST 是规矩的 400，走 PATCH 原来是 500。

    改账时参与人可以从**规则自己点名的人**推出来，而那条路没有再验一次存在性：
    expand() 觉得「规则和参与人对得上」于是放行，一直撞到写 entry_share 才炸外键。
    """
    a, *_ = members
    c = _cat(session)
    e = ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                            amount=100, payer_id=a.id, category_id=c.id)
    with pytest.raises(ledger.LedgerError) as err:
        ledger.update_entry(session, e, actor_id=a.id, version=e.version, fields={},
                            rule={"mode": "exact", "exact": {"99999": 100}})
    assert err.value.code == "unknown_member"


# ---------------------------------------------------------------- 规则里的数字


def test_fractional_weight_is_refused_not_truncated(session: Session, members) -> None:
    """权重 0.5/0.5/1 原来被 int() 截成 0/0/1：前两人一分不出、第三人全担，零提示。

    两边的分摊引擎**本来是挡了的**（split.py 的 _require_int / split.ts 的 requireInt），
    是 expand() 抢在它们前面把证据抹掉。而 TS 那边没有 expand()，于是同一条规则
    前端预览抛错、后端静默存下 —— 正好是那 523 条 fixture 想钉死的事。
    """
    a, b, c_ = members
    cat = _cat(session)
    with pytest.raises(RuleError) as e:
        ledger.create_entry(
            session, actor_id=a.id, kind=EntryKind.expense, on=TODAY, amount=100,
            payer_id=a.id, category_id=cat.id,
            rule={"mode": "ratio", "weights": {str(a.id): 0.5, str(b.id): 0.5, str(c_.id): 1}},
        )
    assert e.value.code == "not_integer"


@pytest.mark.parametrize("bad", [None, "1", {"a": 1}, [1], True])
def test_non_integer_weight_never_becomes_a_500(session: Session, members, bad) -> None:
    """null / 字符串 / 对象 原来让 int() 抛 TypeError，一路冒成 500。"""
    a, b, c_ = members
    cat = _cat(session)
    with pytest.raises(RuleError):
        ledger.create_entry(
            session, actor_id=a.id, kind=EntryKind.expense, on=TODAY, amount=100,
            payer_id=a.id, category_id=cat.id,
            rule={"mode": "ratio", "weights": {str(a.id): bad, str(b.id): 1, str(c_.id): 1}},
        )


# ---------------------------------------------------------------- PATCH 传 null


def test_explicit_null_on_a_required_field_is_refused(session: Session, members) -> None:
    """PATCH 里显式传 null：title 撞 NOT NULL、kind 撞金额校验，两条原来都是 500。"""
    a, *_ = members
    c = _cat(session)
    e = ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                            amount=100, payer_id=a.id, category_id=c.id)
    for field in ("title", "kind", "date", "payer_id", "amount_jpy", "note"):
        with pytest.raises(ledger.LedgerError) as err:
            ledger.update_entry(session, e, actor_id=a.id, version=e.version,
                                fields={field: None})
        assert err.value.code == "null_field"
    # 能清空的那几个不受影响 —— category_id 尤其要能清掉
    ledger.update_entry(session, e, actor_id=a.id, version=e.version,
                        fields={"category_id": None})
    assert session.get(Entry, e.id).category_id is None


# ---------------------------------------------------------------- 出账并发


def test_cutting_again_on_an_empty_draft_makes_no_empty_statement(session: Session, members) -> None:
    """空账单是并发出账的产物：后写的把账全抢走，先出的那张一笔不剩。

    它不会消失 —— 它会一直挂在「已出账」的翻页菜单里（¥0 / 未结清），
    还会当上下一张的 prev，把覆盖期和「固定费默认不带」一起带歪。
    """
    a, *_ = members
    c = _cat(session)
    ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                        amount=1000, payer_id=a.id, category_id=c.id)
    first = cut_statement(session, actor_id=a.id)
    assert len(list(session.exec(select(Entry).where(Entry.statement_id == first.id)))) == 1

    with pytest.raises(BillError) as e:
        cut_statement(session, actor_id=a.id)
    assert e.value.code == "nothing_to_cut"
    # 失败的那次一张单子都不许留下
    assert len(list(session.exec(select(Statement)))) == 1


def test_a_losing_concurrent_cut_leaves_nothing_behind(session: Session, members) -> None:
    """模拟「两个人同时点」：B 先把账目全归走，A 手里那批已经过期了。

    这里直接把 B 的效果做出来（把 statement_id 抢先改掉），再让 A 走完 cut ——
    A 的那条带条件 UPDATE 一笔都认领不到，必须整个回滚，不能留下空单。
    """
    a, *_ = members
    c = _cat(session)
    for _ in range(3):
        ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                            amount=3000, payer_id=a.id, category_id=c.id)
    b_statement = cut_statement(session, actor_id=a.id)         # B 赢了

    with pytest.raises(BillError):
        cut_statement(session, actor_id=a.id)                   # A 才醒过来
    rows = list(session.exec(select(Statement)))
    assert [r.id for r in rows] == [b_statement.id]
    assert len(list(session.exec(select(Entry).where(Entry.statement_id == b_statement.id)))) == 3


# ---------------------------------------------------------------- 密码 / 分类 / 设置（走 HTTP）


def test_overlong_password_is_a_400_not_a_500(client: TestClient, auth) -> None:
    """bcrypt 只认前 72 字节，代码本来就想挡 —— 但抛的是裸 ValueError，没人接，成了 500。

    这是个中日文界面的 App，25 个汉字就是 75 字节，拿一句中文当密码最自然不过。
    """
    me = client.get("/api/auth/me", headers=auth).json()
    r = client.patch(f"/api/members/{me['id']}", headers=auth,
                     json={"password": "密" * 25, "old_password": "pw123456"})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "password_too_long"


def test_category_name_is_stripped_and_unique(client: TestClient, auth) -> None:
    assert client.post("/api/categories", headers=auth,
                       json={"name": "   "}).status_code == 400
    assert client.post("/api/categories", headers=auth,
                       json={"name": " 停车位 "}).status_code == 201
    dup = client.post("/api/categories", headers=auth, json={"name": "停车位"})
    assert dup.status_code == 409, "同名分类在界面上长得一模一样，改哪个删哪个全靠猜"


def test_category_refuses_a_broken_default_rule(client: TestClient, auth) -> None:
    """坏规则原来一声不吭地存下去，等到有人选这个分类记账时才炸 —— 而那句提示
    完全看不出跟分类设置有关。设置面板对 json 类型就是「当场试着用一下」的。"""
    r = client.post("/api/categories", headers=auth,
                    json={"name": "心电感应", "default_rule_json": {"mode": "telepathy"}})
    assert r.status_code == 400
    r = client.post("/api/categories", headers=auth,
                    json={"name": "鬼垫的", "default_payer_id": 99999})
    assert r.status_code == 400


def test_settings_reject_ids_that_point_nowhere(client: TestClient, auth) -> None:
    """member_id_or_null 原来一个校验分支都没匹配上，"不是数字" / 99999 全收。

    存进去之后固定费面板拿它当兜底垫付人，记账当场 400，而报错指向的是账目、
    不是这条设置 —— 人被卡在「记不了账」还找不到原因。
    """
    for bad in (99999, "不是数字", 3.14, [1]):
        r = client.put("/api/settings/default_payer_id", headers=auth, json={"value": bad})
        assert r.status_code == 400, f"{bad!r} 被收下了"
    assert client.put("/api/settings/default_payer_id", headers=auth,
                      json={"value": None}).status_code == 200


def test_text_and_date_have_bounds(session: Session, members) -> None:
    """备注 10k 字、日期 9999-12-31 原来都是收的。

    前者撑爆界面也把库养胖；后者会把草稿账单的覆盖期顶到 9999 年 ——
    而覆盖期就印在账单最上面那一行。
    """
    a, *_ = members
    c = _cat(session)
    mk = lambda **kw: ledger.create_entry(  # noqa: E731
        session, actor_id=a.id, kind=EntryKind.expense, on=kw.pop("on", TODAY),
        amount=100, payer_id=a.id, category_id=c.id, **kw,
    )
    with pytest.raises(ledger.LedgerError) as e:
        mk(title="あ" * (ledger.MAX_TITLE + 1))
    assert e.value.code == "text_too_long"
    with pytest.raises(ledger.LedgerError):
        mk(note="x" * (ledger.MAX_NOTE + 1))
    for bad in (dt.date(9999, 12, 31), dt.date(1900, 1, 1)):
        with pytest.raises(ledger.LedgerError) as e:
            mk(on=bad)
        assert e.value.code == "bad_date"


def test_a_huge_adjustment_cannot_explode_everyones_share(session: Session, members) -> None:
    """**逐条分摊也要有上界。**

    MAX_AMOUNT 只卡 entry.amount_jpy，而真正落库的钱是 entry_share：
    ratio 模式下 base = amount − Σadjustments，一个巨大的调整额能把每个人的应担
    打成天文数字，而**合计仍严格等于 amount** —— 于是「Σ余额≡0」「Σshares≡amount」
    两条自检全绿，屏幕上却看不出哪笔账错了。
    """
    a, b, c_ = members
    cat = _cat(session)
    with pytest.raises((ledger.LedgerError, RuleError)) as e:
        ledger.create_entry(
            session, actor_id=a.id, kind=EntryKind.expense, on=TODAY, amount=1_000,
            payer_id=a.id, category_id=cat.id,
            rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 1},
                  "adjustments": {str(a.id): 10**15}},
        )
    assert e.value.code in ("share_too_large", "not_in_range")

    # exact 模式同理：合计对得上也不行
    with pytest.raises((ledger.LedgerError, RuleError)) as e:
        ledger.create_entry(
            session, actor_id=a.id, kind=EntryKind.expense, on=TODAY, amount=0 or 1,
            payer_id=a.id, category_id=cat.id,
            rule={"mode": "exact", "exact": {str(a.id): 10**15, str(b.id): -10**15 + 1}},
        )
    assert e.value.code in ("share_too_large", "not_in_range")


def test_a_broken_rule_is_refused_when_it_is_saved_not_when_it_is_used(
    client: TestClient, auth
) -> None:
    """规则里的天文数字在**存规则那一刻**就该被拒，而不是等到有人拿它记第一笔账。"""
    r = client.post("/api/categories", headers=auth, json={
        "name": "天文数字", "default_rule_json": {"mode": "ratio", "equal_weight": 10**15},
    })
    assert r.status_code == 400, r.text
    r = client.put("/api/settings/default_rule", headers=auth, json={
        "value": {"mode": "ratio", "equal_weight": 1, "adjustments": {"1": 10**15}},
    })
    assert r.status_code == 400, r.text


def test_an_id_too_big_for_sqlite_is_a_404_not_a_crash(client: TestClient, auth) -> None:
    """超出 int64 的 id：sqlite3 在绑参数那一层抛 OverflowError，不是「查无此行」。

    不接的话，`/api/entries/99999999999999999999` 这种地址（爬虫、手抖、旧链接）
    全都是裸 500。这么大的 id 在这个库里不可能存在，回 404 才是实话。
    """
    huge = 10**20
    for url in (f"/api/entries/{huge}?version=1", f"/api/categories/{huge}", f"/api/memos/{huge}"):
        r = client.patch(url, headers=auth, json={"note": "x"})
        assert r.status_code == 404, (url, r.status_code, r.text)
        assert r.json()["code"] == "not_found"
    assert client.delete(f"/api/entries/{huge}", headers=auth).status_code == 404
    # 外键那一路也一样：payer_id 塞个天文数字
    r = client.post("/api/entries", headers=auth, json={
        "kind": "expense", "date": str(TODAY), "amount_jpy": 100, "payer_id": huge,
    })
    assert r.status_code in (400, 404), r.text


def test_rule_sections_that_are_not_objects_are_refused(client: TestClient, auth) -> None:
    """`weights` / `exact` / `adjustments` 传成数组 —— `.items()` 抛的是裸 500。"""
    for bad in ({"mode": "ratio", "weights": [1, 2, 3]},
                {"mode": "exact", "exact": [100, 200]},
                {"mode": "ratio", "equal_weight": 1, "adjustments": "1:100"}):
        r = client.post("/api/categories", headers=auth,
                        json={"name": f"坏规则{bad['mode']}{len(str(bad))}", "default_rule_json": bad})
        assert r.status_code == 400, (bad, r.status_code, r.text)


def test_clearing_a_not_null_column_is_refused_on_categories_and_memos(
    client: TestClient, auth
) -> None:
    """PATCH 里显式传 null：entries / members 上一轮堵过，这两处漏了。

    不挡就是 NOT NULL 约束在 commit 那一刻炸，冒到顶变成「服务器出错了」，
    人根本不知道是自己哪个字段传空了。
    """
    cid = client.post("/api/categories", headers=auth, json={"name": "可清空"}).json()["id"]
    mid = client.post("/api/memos", headers=auth, json={"title": "备忘"}).json()["id"]
    for url, body in ((f"/api/categories/{cid}", {"icon": None}),
                      (f"/api/categories/{cid}", {"archived": None}),
                      (f"/api/memos/{mid}", {"body": None})):
        r = client.patch(url, headers=auth, json=body)
        assert r.status_code == 400, (url, body, r.status_code, r.text)
        assert r.json()["code"] == "null_field"
        # detail 是要直接插进界面文案的，得是一句话不是数组
        assert isinstance(r.json()["detail"]["fields"], str)
    # 能清空的那两个照旧放行
    assert client.patch(f"/api/categories/{cid}", headers=auth,
                        json={"default_payer_id": None}).status_code == 200


def test_the_opening_balance_is_read_in_one_statement(session: Session, members) -> None:
    """上期结转必须**一条 SQL 数完** —— 一条语句才是一个快照。

    分成「垫付」「应担」两条 SELECT 的话它们各取各的最新状态（pysqlite 不为 SELECT
    开事务）。别人在这两条之间改了一笔已出账的账，这边就数到了新的垫付、旧的应担，
    算出一本不平的账，GET /api/bill 当场 500。
    实测：旧写法在「一边改已出账的账、一边看账单」6 秒里 3582 次读炸了 248 次，
    改成一条 UNION ALL 之后 3420 次读 0 次。这里钉的就是「别再拆回两条」。
    """
    from sqlalchemy import event

    a, *_ = members
    cat = _cat(session)
    for i in range(3):
        ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                            amount=1000 + i, payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id, label="上一期", on=TODAY)

    seen: list[str] = []
    bind = session.get_bind()

    def _count(conn, cursor, statement, *args):  # noqa: ANN001, ARG001
        seen.append(statement)

    event.listen(bind, "before_cursor_execute", _count)
    try:
        opening = bill._opening(session, None)
    finally:
        event.remove(bind, "before_cursor_execute", _count)

    assert opening, "这一期之前确实有账，结转不该是空的"
    # 一条数 statement 的（_earlier_ids，草稿时不查）+ 一条数钱的
    assert len(seen) == 1, "\n---\n".join(seen)


def test_two_people_opening_the_bill_page_at_once_do_not_double_the_rent(tmp_path) -> None:
    """群里一句「出账了」，三个人同时点开账单页 —— 房租不能记两笔。

    账单页一挂载就 POST /api/monthly/carry（MonthlyFixed.vue 的 onMounted）。
    「读一遍本期已经有哪几项 → 把缺的记上」中间隔着几十毫秒，两个请求都会在对方
    commit 之前读到「本期还没记房租」。面板一行只显示得下一笔，所以屏幕上金额是对的、
    合计是两倍 —— 用户得自己去账目列表里翻出那笔重复的删掉。

    用真文件库 + 两条连接：内存库那套 StaticPool 只有一条连接，会把这个race 盖住。
    """
    import threading

    from sqlmodel import SQLModel, create_engine

    from app.services import settings as settings_svc
    from app.services.settings import seed_settings

    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_settings(s)
        settings_svc.set_(s, "backup_path", str(tmp_path / "backups"))
        a = Member(name="a", display_name="A", display_order=0, joined_on=dt.date(2026, 1, 1))
        s.add(a)
        s.commit()
        s.refresh(a)
        aid = a.id
        cat = Category(name="房租", monthly=True, same_as_last=True, default_payer_id=aid)
        s.add(cat)
        s.commit()
        s.refresh(cat)
        cid = cat.id
        ledger.create_entry(s, actor_id=aid, kind=EntryKind.expense, on=TODAY,
                            amount=90_000, payer_id=aid, category_id=cid)
        cut_statement(s, actor_id=aid, label="上一期", on=TODAY)

    gate = threading.Barrier(2)

    def go() -> None:
        with Session(engine) as s:
            gate.wait()
            bill.carry_same_as_last(s, actor_id=aid)

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    with Session(engine) as s:
        draft = [e for e in bill.unbilled(s) if e.category_id == cid]
    assert len(draft) == 1, f"本期房租记了 {len(draft)} 笔，当期账单凭空翻倍"


def test_fixing_an_old_bill_does_not_switch_this_months_carry_off(session: Session, members) -> None:
    """回头删掉一笔**已经出过账**的固定费，不该让本期的「和上期一样」停摆。

    已出账的账目软删之后 statement_id 还留着；「本期删掉的不碰」那一条只该认草稿里的。
    分不开的话：9 月初去把 8 月手滑多记的那笔房租删了 → 整个 9 月房租都不再自动记，
    而它既不进 created 也不进 failed，屏幕上一句提示都没有，出账时按 0 结。
    """
    a, *_ = members
    cat = Category(name="房租", monthly=True, same_as_last=True, default_payer_id=a.id)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    for _ in range(2):
        ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=TODAY,
                            amount=120_000, payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id, label="8 月", on=TODAY)

    extra = session.exec(
        select(Entry).where(Entry.category_id == cat.id).order_by(Entry.id.desc())
    ).first()
    ledger.delete_entry(session, entry=extra, actor_id=a.id)

    out = bill.carry_same_as_last(session, actor_id=a.id)
    assert [c["name"] for c in out["created"]] == ["房租"], out
