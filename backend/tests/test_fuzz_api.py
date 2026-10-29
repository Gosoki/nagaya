"""走真接口的随机操作序列 —— test_invariants 的上一层。

test_invariants 直接调 service，只看 Σ余额、Σshares、Σclosing。这次审计里漏网的两条
「已出账单悄悄变了」都是**跨层、跨时间**的：要先出账、再改更早的账、再有人搬走……
只有把真实会发生的事按接口一层一层叠起来才撞得出来。

这里每个请求一个独立的 Session（和线上一样），每个 seed 一个临时文件库，「今天」是假的、
会往前走。操作池：记支出 / 收入 / 转账 / 帮买、幂等键重放、改、删、恢复、出账（含不含固定费）、
「确认已完成」（草稿和已出的）、照上期、改设置、成员搬走 / 回来、过几天。

每一步之后做便宜的检查（逐笔 Σ分摊 ＝ 金额、Σ余额 ＝ 0、转账形状、冻结快照没被动过、
没有 500）；每 25 步和最后一步做全套：逐张账单的行算术、上期结转首尾相接、方案能清零、
列表那两个数和逐张算的一致、帮买独立重算、「出账后被改过」为空时冻结快照和此刻一字不差。

确定性的：没有线程、没有真时间（真并发单独在文件末尾两条里用 Barrier 撞）。红了的话
报错里带着 seed 和 step，原地就能复现。规模按「整套测试多 20 秒以内」定。
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
import sys
import threading
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth import make_token
from app.db import get_session
from app.init_db import DEFAULT_CATEGORIES
from app.main import app as fastapi_app
from app.models import Category, Member, Statement
from app.services import bill as bill_svc
from app.services import ledger
from app.services import settings as settings_svc
from app.services.settings import seed_settings

#: 6 条序列 × 150 步，约 10 秒
SEEDS = range(1, 7)
STEPS = 150
#: 全套检查的间隔（步）
FULL_EVERY = 25

APP = Path(__file__).resolve().parents[1] / "app"


# ---------------------------------------------------------------- 「今天」：一处打补丁，全都打到


def _modules_using_today() -> set[str]:
    """app 里所有提到 today_jst 的模块（照源码扫，不手抄名单）"""
    out = set()
    for f in APP.rglob("*.py"):
        if re.search(r"\btoday_jst\b", f.read_text(encoding="utf-8")):
            out.add("app." + ".".join(f.relative_to(APP).with_suffix("").parts))
    return out


@pytest.fixture
def fake_today(monkeypatch: pytest.MonkeyPatch) -> dict:
    """把 app 里每一处 today_jst 换成一个会往前走的假日子。

    「哪几个模块要打补丁」照源码扫出来：原来要手抄七处（models、三个 service、三个 router），
    以后新加一个模块 import 了 today_jst 却忘了加进名单，测试就悄悄用回真实日期 ——
    今天跑是绿的，过两个月可能就红了。下面那条守卫钉着「扫到的都打上了」
    """
    clock = {"today": dt.date(2026, 3, 1)}
    patched = set()
    for name in _modules_using_today():
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "today_jst"):
            monkeypatch.setattr(mod, "today_jst", lambda: clock["today"])
            patched.add(name)
    clock["patched"] = patched
    return clock


def test_every_module_that_uses_today_gets_the_fake_one(fake_today: dict) -> None:
    using = _modules_using_today()
    assert "app.models" in using and "app.services.ledger" in using, "扫描写坏了会空跑成假绿"
    assert using == fake_today["patched"], f"这几个模块没打上假日子：{using - fake_today['patched']}"


# ---------------------------------------------------------------- 一个 seed 一本账


@pytest.fixture
def ledger_factory(tmp_path: Path):  # noqa: ANN201
    """每次调用给一本新账：临时文件库 + 每个请求一个独立 Session + 三个人的 token"""
    made: list = []

    def make(name: str) -> tuple:
        engine = create_engine(f"sqlite:///{tmp_path / name}.db", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            seed_settings(s)
            settings_svc.set_(s, "backup_every_hours", 0)
            s.add_all([
                Category(name=n, icon=i, color=c, monthly=m, display_order=o)
                for o, (n, i, c, m) in enumerate(DEFAULT_CATEGORIES)
            ])
            people = [Member(name=n, display_name=n.title(), display_order=i, joined_on=dt.date(2026, 1, 1))
                      for i, n in enumerate(("go", "kan", "zen"))]
            s.add_all(people)
            s.commit()
            cats = {c.name: c for c in s.exec(select(Category))}
            rent = cats["房租"]
            rent.default_rule_json = {"mode": "ratio", "equal_weight": 1,
                                      "adjustments": {str(people[0].id): 5_000, str(people[2].id): -5_000}}
            rent.same_as_last = True
            rent.default_payer_id = people[2].id
            cats["网费"].same_as_last = True
            s.add_all([rent, cats["网费"]])
            s.commit()
            tokens = {m.id: make_token(m) for m in people}

        def per_request():  # noqa: ANN202
            with Session(engine) as s:
                yield s

        fastapi_app.dependency_overrides[get_session] = per_request
        made.append(engine)
        return engine, tokens

    yield make
    fastapi_app.dependency_overrides.clear()
    for e in made:
        e.dispose()


class Fuzz:
    OPS = [("add", 22), ("income", 3), ("transfer", 5), ("helpbuy", 4), ("replay", 4), ("update", 13),
           ("delete", 5), ("restore", 3), ("cut", 7), ("confirm", 8), ("carry", 4), ("settings", 2),
           ("member", 3), ("tick", 10)]

    def __init__(self, seed: int, engine, tokens: dict[int, str], clock: dict) -> None:  # noqa: ANN001
        self.seed, self.engine, self.tokens, self.clock = seed, engine, tokens, clock
        self.rng = random.Random(seed)
        self.client = TestClient(fastapi_app, raise_server_exceptions=False)
        self.frozen: dict[int, str] = {}       # 账单 id → 出账那一刻的 snapshot_json 原文
        self.keyed: list[tuple[dict, int]] = []  # 带幂等键记过的：(请求体, 那一笔的 id)
        self.step = -1
        self.op = ""
        self.bad: list[str] = []

    # ------------------------------------------------------------ 小工具

    @property
    def today(self) -> dt.date:
        return self.clock["today"]

    def fail(self, what: str) -> None:
        self.bad.append(f"seed={self.seed} step={self.step} op={self.op}：{what}")

    def sql(self, q: str) -> list:
        with Session(self.engine) as s:
            return list(s.exec(text(q)))

    def req(self, method: str, url: str, who: int | None = None, **kw):  # noqa: ANN201
        who = who if who in self.tokens else self.rng.choice(sorted(self.tokens))
        r = self.client.request(method, url, headers={"Authorization": f"Bearer {self.tokens[who]}"}, **kw)
        if r.status_code >= 500:
            self.fail(f"{method} {url} {kw.get('json')} → {r.status_code} {r.text[:300]}")
        return r

    def members(self) -> list[Member]:
        with Session(self.engine) as s:
            return list(s.exec(select(Member).order_by(Member.display_order, Member.id)))

    def active(self) -> list[int]:
        return [m.id for m in self.members() if m.is_active(self.today)]

    def categories(self) -> list[dict]:
        return self.req("GET", "/api/categories", params={"include_archived": True}).json()

    def rule(self, ids: list[int]) -> dict:
        w = {str(i): self.rng.choice([0, 1, 1, 2, 3]) for i in ids}
        if not any(w.values()):
            w[str(self.rng.choice(ids))] = 1
        out: dict = {"mode": "ratio", "weights": w}
        if self.rng.random() < 0.3:
            out["adjustments"] = {str(self.rng.choice(ids)): self.rng.randint(-5_000, 5_000)}
        return out

    def date(self) -> str:
        return (self.today - dt.timedelta(days=self.rng.randint(0, 20))).isoformat()

    def count(self) -> int:
        return self.sql("select count(*) from entry")[0][0]

    # ------------------------------------------------------------ 操作

    def op_add(self, kind: str = "expense") -> None:
        act = self.active()
        payer = self.rng.choice(act)
        amount = self.rng.choice([self.rng.randint(1, 50), self.rng.randint(100, 30_000),
                                  self.rng.randint(30_000, 150_000)])
        body: dict = {"kind": kind, "date": self.date(), "payer_id": payer, "title": f"t{self.step}"}
        if kind == "expense":
            body["amount_jpy"] = amount
            pool = [c for c in self.categories() if not c["archived"]]
            daily = [c for c in pool if not c["monthly"]]
            monthly = [c for c in pool if c["monthly"]]
            roll = self.rng.random()
            if roll < 0.65:
                body["category_id"] = self.rng.choice(daily)["id"]
            elif roll < 0.9:
                body["category_id"] = self.rng.choice(monthly)["id"]
                body["confirm_jump"] = self.rng.random() < 0.7     # 量级闸问过一句之后人点了确定
        elif kind == "income":
            body["amount_jpy"] = -amount
        else:
            body["amount_jpy"] = amount
            body["to_member_id"] = self.rng.choice([i for i in act if i != payer])
        if kind != "settlement":
            roll = self.rng.random()
            if roll < 0.4:
                body["rule"] = self.rule(act)
            elif roll < 0.55:
                sub = self.rng.sample(act, self.rng.randint(1, len(act)))
                body["member_ids"], body["rule"] = sub, self.rule(sub)
        if self.rng.random() < 0.5:
            body["client_key"] = f"k{self.seed}-{self.step}-{self.rng.randint(0, 10**9)}"
        n = self.count()
        r = self.req("POST", "/api/entries", who=payer, json=body)
        if r.status_code == 201:
            e = r.json()
            if sum(e["shares"].values()) != e["amount_jpy"]:
                self.fail(f"返回的分摊合计 ≠ 金额：{e}")
            if "client_key" in body:
                self.keyed.append((body, e["id"]))
        elif r.status_code < 500 and self.count() != n:
            self.fail(f"被拒（{r.status_code} {r.json().get('code')}）却留下了一笔")

    def op_income(self) -> None:
        self.op_add("income")

    def op_transfer(self) -> None:
        self.op_add("settlement")

    def op_helpbuy(self) -> None:
        act = self.active()
        payer, who = self.rng.sample(act, 2)
        amount = self.rng.randint(100, 20_000)
        r = self.req("POST", "/api/entries", who=payer, json={
            "kind": "expense", "date": self.date(), "amount_jpy": amount, "payer_id": payer,
            "member_ids": [who], "rule": {"mode": "ratio", "weights": {str(who): 1}}, "title": f"帮买{self.step}",
        })
        if r.status_code == 201 and {k: v for k, v in r.json()["shares"].items() if v} != {str(who): amount}:
            self.fail(f"帮买不是全算在那一个人头上：{r.json()['shares']}")

    def op_replay(self) -> None:
        """离线草稿补交：同一个键再来一次，不许多记一笔（删掉了的就说删掉了）"""
        if not self.keyed:
            return
        body, eid = self.rng.choice(self.keyed)
        n = self.count()
        r = self.req("POST", "/api/entries", json=body)
        if self.count() != n:
            self.fail(f"重放幂等键多记了 {self.count() - n} 笔")
        if r.status_code == 201 and r.json()["id"] != eid:
            self.fail(f"重放还回来的是 #{r.json()['id']}，不是原来那笔 #{eid}")

    def pick(self, deleted: bool = False) -> dict | None:
        rows = [dict(r._mapping) for r in self.sql(
            f"select * from entry where deleted_at is {'not ' if deleted else ''}null order by id")]
        return self.rng.choice(rows) if rows else None

    def op_update(self) -> None:
        e = self.pick()
        if e is None:
            return
        act = self.active()
        body: dict = {}
        if self.rng.random() < 0.6:
            a = self.rng.randint(1, 120_000)
            body["amount_jpy"] = -a if e["kind"] == "income" else a
        if self.rng.random() < 0.2:
            body["date"] = self.date()
        if self.rng.random() < 0.2:
            payer = self.rng.choice(act)
            if e["kind"] != "settlement" or payer != e["to_member_id"]:
                body["payer_id"] = payer
        if e["kind"] != "settlement" and self.rng.random() < 0.25:
            body["rule"] = self.rule(act)
        body.setdefault("title", f"u{self.step}")
        body["confirm_jump"] = True
        stale = self.rng.random() < 0.1
        r = self.req("PATCH", f"/api/entries/{e['id']}",
                     params={"version": e["version"] - 1 if stale else e["version"]}, json=body)
        if stale and r.status_code == 200:
            self.fail(f"拿着旧 version 改 #{e['id']} 居然改成了")

    def op_delete(self) -> None:
        e = self.pick()
        if e is None:
            return
        stale = self.rng.random() < 0.15
        r = self.req("DELETE", f"/api/entries/{e['id']}", params={"version": e["version"] - (1 if stale else 0)})
        if stale and r.status_code == 204:
            self.fail(f"拿着旧 version 删 #{e['id']} 居然删成了")

    def op_restore(self) -> None:
        e = self.pick(deleted=True)
        if e is not None:
            self.req("POST", f"/api/entries/{e['id']}/restore")

    def op_cut(self) -> None:
        latest = self.sql("select id from statement order by cut_at desc limit 1")
        params = {"include_monthly": self.rng.random() < 0.75}
        if self.rng.random() < 0.5:
            params["after_statement_id"] = latest[0][0] if latest else 0
        bal = self.balances()
        r = self.req("POST", "/api/statements", params=params)
        if r.status_code != 201:
            return
        sid = r.json()["id"]
        self.frozen[sid] = self.sql(f"select snapshot_json from statement where id = {sid}")[0][0]
        if self.balances() != bal:
            self.fail("出账动了余额")
        snap = json.loads(self.frozen[sid])
        self.clears({m["member_id"]: m["closing"] for m in snap["members"]}, snap["transfers"], f"第 {sid} 张冻结的方案")

    def op_confirm(self) -> None:
        sts = [r[0] for r in self.sql("select id from statement order by cut_at desc")]
        target = None
        if sts and self.rng.random() < 0.5:
            target = sts[0] if self.rng.random() < 0.6 else self.rng.choice(sts)
        b = self.req("GET", "/api/bill" if target is None else f"/api/statements/{target}/bill")
        if b.status_code != 200:
            return
        b = b.json()
        cands = []
        for i, t in enumerate(b["transfers"]):     # 和前端 leftOf 同一个口径
            rest = t["amount"] - (b["settled_paid"][i] if i < len(b["settled_paid"]) else 0)
            live = next((x["amount"] for x in b["live_transfers"]
                         if (x["from_id"], x["to_id"]) == (t["from_id"], t["to_id"])), 0)
            if max(0, min(rest, live)) > 0:
                cands.append((t, max(0, min(rest, live))))
        if not cands:
            return
        t, left = self.rng.choice(cands)
        amount = left if self.rng.random() < 0.7 else max(1, left // 2)
        bal = self.balances()
        r = self.req("POST", "/api/bill/confirm", who=t["from_id"], json={
            "statement_id": target, "from_id": t["from_id"], "to_id": t["to_id"],
            "amount": amount, "expect_left": left, "date": self.today.isoformat(),
        })
        if r.status_code == 409:
            self.fail(f"前端算的还差 {left}，后端不认：{r.json()}")
        elif r.status_code == 201:
            bal[t["from_id"]] = bal.get(t["from_id"], 0) + amount
            bal[t["to_id"]] = bal.get(t["to_id"], 0) - amount
            if {k: v for k, v in bal.items() if v} != {k: v for k, v in self.balances().items() if v}:
                self.fail("确认已完成之后的余额变化 ≠ 这一笔转账")

    def op_carry(self) -> None:
        m = self.req("GET", "/api/monthly")
        if m.status_code != 200:
            return
        ready = {r["category_id"]: r for r in m.json()["rows"] if r.get("carry_amount")}
        if not ready:
            return
        latest = self.sql("select id from statement order by cut_at desc limit 1")
        before = {r[0] for r in self.sql("select id from entry")}
        r = self.req("POST", "/api/monthly/carry", json={
            "category_ids": sorted(ready), "after_statement_id": latest[0][0] if latest else 0,
        })
        if r.status_code != 200:
            return
        new = [dict(x._mapping) for x in self.sql("select * from entry") if x.id not in before]
        if len(new) != len(r.json()["created"]):
            self.fail(f"照上期说记了 {len(r.json()['created'])} 笔，库里多了 {len(new)} 笔")
        act = set(self.active())
        for e in new:
            if e["amount_jpy"] != ready[e["category_id"]]["carry_amount"]:
                self.fail(f"照上期记的 {e['amount_jpy']} ≠ 按钮上写的 {ready[e['category_id']]['carry_amount']}")
            if e["payer_id"] not in act:
                self.fail(f"照上期记成了不在籍的人垫的：#{e['id']}")

    def op_settings(self) -> None:
        key, value = self.rng.choice([("simplify_debts", True), ("simplify_debts", False),
                                      ("remainder_to", "payer"), ("remainder_to", "order"),
                                      ("remainder_to", "rotate")])
        self.req("PUT", f"/api/settings/{key}", json={"value": value})

    def op_member(self) -> None:
        ms = self.members()
        gone = [m for m in ms if m.left_on is not None]
        if gone and self.rng.random() < 0.4:
            self.req("PATCH", f"/api/members/{self.rng.choice(gone).id}", json={"left_on": None})
            return
        act = self.active()
        if len([m for m in ms if m.left_on is None]) <= 2 or len(act) <= 2:
            return
        m = self.rng.choice(act)
        left = max(self.today + dt.timedelta(days=self.rng.randint(-6, 6)), dt.date(2026, 1, 1))
        self.req("PATCH", f"/api/members/{m}", json={"left_on": left.isoformat()})

    def op_tick(self) -> None:
        self.clock["today"] += dt.timedelta(days=self.rng.choice([0, 1, 1, 2, 3, 5, 9]))

    # ------------------------------------------------------------ 检查

    def balances(self) -> dict[int, int]:
        return {int(k): v for k, v in self.req("GET", "/api/balances").json()["balances"].items()}

    def clears(self, closing: dict, transfers: list[dict], tag: str) -> None:
        left = {int(k): v for k, v in closing.items()}
        for t in transfers:
            if t["amount"] <= 0:
                self.fail(f"{tag}里有不是正数的一笔：{t}")
            left[t["from_id"]] = left.get(t["from_id"], 0) + t["amount"]
            left[t["to_id"]] = left.get(t["to_id"], 0) - t["amount"]
        if any(left.values()):
            self.fail(f"{tag}套到结余上清不了零：结余 {closing} 方案 {transfers} 剩 {left}")

    def cheap(self) -> None:
        bad = self.sql(
            "select e.id from entry e left join entry_share s on s.entry_id = e.id group by e.id "
            "having coalesce(sum(s.amount_jpy), 0) != e.amount_jpy")
        if bad:
            self.fail(f"分摊合计 ≠ 金额：{[r[0] for r in bad][:5]}")
        bad = self.sql(
            "select e.id from entry e join entry_share s on s.entry_id = e.id "
            "where e.kind = 'settlement' and s.member_id != e.to_member_id")
        if bad:
            self.fail(f"转账的分摊不在转入人头上：{[r[0] for r in bad][:5]}")
        with Session(self.engine) as s:
            if sum(ledger.balances(s).values()):
                self.fail("Σ余额 ≠ 0")
        for sid, snap in self.sql("select id, snapshot_json from statement"):
            if sid in self.frozen and self.frozen[sid] != snap:
                self.fail(f"第 {sid} 张的冻结快照被改了")

    def bill_rows(self, b: dict, tag: str) -> None:
        rows = b["members"]
        for r in rows:
            if r["opening"] + r["paid"] - r["owed"] + r["transferred_out"] - r["transferred_in"] != r["closing"]:
                self.fail(f"{tag} 每人行的加减对不上：{r}")
        for key in ("opening", "closing"):
            if sum(r[key] for r in rows):
                self.fail(f"{tag} Σ{key} ≠ 0")
        total = b["total_expense"] + b["total_income"]
        if sum(r["paid"] for r in rows) != total or sum(r["owed"] for r in rows) != total:
            self.fail(f"{tag} Σ垫付 / Σ应担 ≠ 支出 + 收入")
        if b["help_total"] != sum(h["amount"] for h in b["help_items"]):
            self.fail(f"{tag} 帮买合计 ≠ 逐笔之和")
        if b["is_draft"]:
            self.clears({r["member_id"]: r["closing"] for r in rows}, b["transfers"], f"{tag} 的方案")
        self.clears(b["live_closing"], b["live_transfers"], f"{tag} 此刻的方案")
        # 帮买独立重算：支出、不挂固定费、只有一个人担而且不是付款人
        where = "statement_id is null" if b["is_draft"] else f"statement_id = {b['statement_id']}"
        fixed = {c["id"] for c in self.categories() if c["monthly"]}
        mine = []
        for e in self.sql(f"select id, payer_id, category_id from entry where {where} "
                          "and deleted_at is null and kind = 'expense'"):
            if e.category_id in fixed:
                continue
            bearers = [r[0] for r in self.sql(f"select member_id from entry_share where entry_id = {e.id} "
                                              "and amount_jpy != 0")]
            if len(bearers) == 1 and bearers[0] != e.payer_id:
                mine.append(e.id)
        if sorted(mine) != sorted(h["entry_id"] for h in b["help_items"]):
            self.fail(f"{tag} 帮买认得不对：重算 {mine}，账单 {[h['entry_id'] for h in b['help_items']]}")

    def full(self) -> None:
        nz = lambda d: {k: v for k, v in d.items() if v}  # noqa: E731
        draft = self.req("GET", "/api/bill")
        if draft.status_code != 200:
            return
        draft = draft.json()
        self.bill_rows(draft, "草稿")
        bal = nz(self.balances())
        if nz({int(k): v for k, v in draft["live_closing"].items()}) != bal:
            self.fail("草稿的结余 ≠ 账本余额")
        with Session(self.engine) as s:
            sts = list(s.exec(select(Statement).order_by(Statement.cut_at, Statement.id)))
            totals = bill_svc.list_totals(s)
            settled = bill_svc.list_settled(s, sts)
        prev: dict[int, int] = {}
        for st in sts:
            r = self.req("GET", f"/api/statements/{st.id}/bill")
            if r.status_code != 200:
                prev = {}
                continue
            b = r.json()
            tag = f"第 {st.id} 张"
            self.bill_rows(b, tag)
            if nz({r_["member_id"]: r_["opening"] for r_ in b["members"]}) != prev:
                self.fail(f"{tag} 的上期结转 ≠ 上一张的结余")
            prev = nz({r_["member_id"]: r_["closing"] for r_ in b["members"]})
            if nz({int(k): v for k, v in b["live_closing"].items()}) != bal:
                self.fail(f"{tag} 此刻那一列 ≠ 账本余额")
            if totals.get(st.id, 0) != b["total_expense"]:
                self.fail(f"{tag} 列表上的合计 {totals.get(st.id)} ≠ 账单上的 {b['total_expense']}")
            if settled.get(st.id) != b["settled"]:
                self.fail(f"{tag} 列表上的「已结清」和账单上的不一样")
            if b["edited_after_cut"] is None:
                # 没挂「出账后被改过」＝ 和出账那一刻一字不差。差了却不挂，就是「已出的账单悄悄变了」
                snap = json.loads(self.frozen[st.id]) if st.id in self.frozen else (st.snapshot_json or {})
                then = {m["member_id"]: m for m in snap["members"]}
                now = {m["member_id"]: m for m in b["members"]}
                diffs = [(mid, k) for mid in then.keys() | now.keys()
                         for k in ("opening", "owed", "paid", "transferred_out", "transferred_in", "closing")
                         if then.get(mid, {}).get(k, 0) != now.get(mid, {}).get(k, 0)]
                diffs += [k for k in ("total_expense", "total_income", "help_total", "entry_count")
                          if snap.get(k) != b.get(k)]
                if diffs:
                    self.fail(f"{tag} 没标「出账后被改过」，可和出账那一刻不一样了：{diffs[:6]}")
        if nz({r_["member_id"]: r_["opening"] for r_ in draft["members"]}) != prev:
            self.fail("草稿的上期结转 ≠ 最近一张的结余")

    def run(self) -> list[str]:
        names = [o for o, _ in self.OPS]
        weights = [w for _, w in self.OPS]
        for self.step in range(STEPS):
            self.op = self.rng.choices(names, weights)[0]
            getattr(self, f"op_{self.op}")()
            self.cheap()
            if self.step % FULL_EVERY == FULL_EVERY - 1 or self.step == STEPS - 1:
                self.full()
            if self.bad:
                break                        # 第一处就停：后面的多半是它的连锁反应
        return self.bad


@pytest.mark.parametrize("seed", SEEDS)
def test_random_api_sequences_keep_every_invariant(seed: int, ledger_factory, fake_today: dict) -> None:
    engine, tokens = ledger_factory(f"fuzz{seed}")
    bad = Fuzz(seed, engine, tokens, fake_today).run()
    assert not bad, "\n".join(bad[:5])


# ---------------------------------------------------------------- 真并发：两台手机同一瞬间


def _two_at_once(*calls) -> list:  # noqa: ANN002
    out: list = [None] * len(calls)
    gate = threading.Barrier(len(calls))

    def go(i: int) -> None:
        gate.wait()
        out[i] = calls[i]()

    threads = [threading.Thread(target=go, args=(i,)) for i in range(len(calls))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_two_identical_confirms_at_the_same_instant_record_one_transfer(ledger_factory, fake_today) -> None:
    """转出方和转入方同时点「确认已完成」（或者一个人的「确定」连点两下，两个请求一起到）：
    「算此刻还差多少 → 记账」在一把锁里，只许一笔成。这把锁原来一条真并发的用例都没有"""
    engine, tokens = ledger_factory("confirm")
    go, kan, _ = sorted(tokens)
    auth = lambda m: {"Authorization": f"Bearer {tokens[m]}"}  # noqa: E731
    c1 = TestClient(fastapi_app, raise_server_exceptions=False)
    c2 = TestClient(fastapi_app, raise_server_exceptions=False)
    r = c1.post("/api/entries", headers=auth(go), json={
        "kind": "expense", "date": fake_today["today"].isoformat(), "amount_jpy": 30_000, "payer_id": go})
    assert r.status_code == 201
    t = c1.get("/api/bill", headers=auth(go)).json()["transfers"][0]
    body = {"from_id": t["from_id"], "to_id": t["to_id"], "amount": t["amount"], "expect_left": t["amount"]}
    for _ in range(3):
        before = Counter(e["kind"] for e in c1.get("/api/entries", headers=auth(go)).json())["settlement"]
        res = _two_at_once(lambda: c1.post("/api/bill/confirm", headers=auth(go), json=body),
                           lambda: c2.post("/api/bill/confirm", headers=auth(kan), json=body))
        codes = sorted(x.status_code for x in res)
        after = Counter(e["kind"] for e in c1.get("/api/entries", headers=auth(go)).json())["settlement"]
        if codes == [201, 409]:
            assert after == before + 1
            return
        # 两个都 409 只可能是上一轮已经转清了；重新取一个还没转的
        assert codes == [409, 409] and after == before, codes
    pytest.fail("三轮里一次都没撞出「一成一败」")


def test_two_cuts_at_the_same_instant_make_one_statement(ledger_factory, fake_today) -> None:
    """两个人同时点「出账单」：只许出一张，另一个拿到 409 / 400，不许留下空单、不许把账分成两半"""
    engine, tokens = ledger_factory("cut")
    go, kan, _ = sorted(tokens)
    auth = lambda m: {"Authorization": f"Bearer {tokens[m]}"}  # noqa: E731
    c1 = TestClient(fastapi_app, raise_server_exceptions=False)
    c2 = TestClient(fastapi_app, raise_server_exceptions=False)
    for amount in (3_000, 4_000, 5_000):
        assert c1.post("/api/entries", headers=auth(go), json={
            "kind": "expense", "date": fake_today["today"].isoformat(), "amount_jpy": amount,
            "payer_id": go}).status_code == 201
    res = _two_at_once(lambda: c1.post("/api/statements", headers=auth(go)),
                       lambda: c2.post("/api/statements", headers=auth(kan)))
    assert sorted(x.status_code for x in res)[0] == 201 and all(x.status_code < 500 for x in res), \
        [(x.status_code, x.text[:200]) for x in res]
    with Session(engine) as s:
        sts = list(s.exec(select(Statement)))
        assert len(sts) == 1, "两张单子：一张有账、一张是空的，或者账被分成两半"
        assert bill_svc.build_bill(s, sts[0])["entry_count"] == 3
