"""生产体检：只读，在一份一致快照上把账本最要紧的几条恒等式和几张「要人看一眼」的清单过一遍。

    .venv/bin/python -m tools.checkup                      # 体检现在的账本
    .venv/bin/python -m tools.checkup --file=某份备份.db    # 体检任意一份备份（拷回 Mac 上也能跑）
    .venv/bin/python -m tools.checkup --all                # 每一项的命中全部列出（默认每项列 8 条）

Docker 下：`docker compose exec nagaya .venv/bin/python -m tools.checkup`。

**为什么要有它**：生产上的库谁都不会天天去翻。账平不平、有没有绕过 app 改过的行、
备份里有而活库里没了的账、搬走的人是不是还欠着钱 —— 平时一样都看不见，
真出事的那天只表现成账单页一个查不出原因的 500。

**怎么保证只读**：
  1. 标准库 sqlite3 以 mode=ro 打开账本，VACUUM INTO 一份到临时目录（0700）——
     一瞬间的一致快照，不挡别人记账，活库一个字节都不动；
  2. 之后的检查全在快照上跑。要用 app 服务层的那几项，先把 NAGAYA_DB 指到快照再 import；
     不 import app.auth（缺 .secret 时它会自己生成一个）；
  3. 不管怎么退出（包括 Ctrl-C），临时目录都删掉：那是整本账的明文。

报告分三段：
  「必须修」   恒等式。哪条没过就是账本坏了或者被人绕过 app 改过，退出码 1。
              这次没法比的（比如 I1 没有可比的备份）印「没比」和原因，不印「通过」。
  「要人核对」 只列出来，不改、不判对错 —— 是不是问题要人来定。按时间排的新的在前。
  「仅供参考」 已经定过、或者还挂着等人拍板的事（同盘、逐笔轮转、出账后被改过），
              还有几个环境数字。只打印，不算命中，不影响退出码。

阈值先写成下面的模块常量：等用法稳了、真要在面板上调，再登记进 settings_spec。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]

#: 固定费「疑似漏填」：前 E1_WINDOW 张结了固定费的账单里至少 E1_MIN_HITS 张有这一项，这张却没有。
#: 隔月收的水费 6 张里只有 3 张，不报
E1_WINDOW = 6
E1_MIN_HITS = 5
#: 每一项最多列几条样本（全部的条数照实说；--all 全列）
SAMPLES = 8
#: 从环境变量给的签名密钥短于这么多字节，在「仅供参考」里提一句（和 app.auth 同一条线）
MIN_SECRET_BYTES = 32
#: 库里的时刻是 naive UTC，印给人看一律换成日本时间 —— app 里账单标的「10/29 出账」就是按它算的
JST = dt.timezone(dt.timedelta(hours=9))
USAGE = "用法：python -m tools.checkup [--file=备份.db | --file 备份.db] [--all]"


class Report:
    """三段报告。P0 每一项都打印（通过的也打，好知道查过什么；没比的打「没比」）；其余只打有东西的"""

    def __init__(self) -> None:
        #: (编号, 标题, 命中, 没比的原因)。原因不是 None ＝ 这次没比
        self.must: list[tuple[str, str, list[str], str | None]] = []
        self.review: list[tuple[str, str, list[str]]] = []
        self.info: list[str] = []

    def p0(self, code: str, title: str, hits: list[str]) -> None:
        self.must.append((code, title, hits, None))

    def skip(self, code: str, title: str, why: str) -> None:
        """这一项这次**没比**。不能记成一条空的 p0 —— 那会印成「通过」，而「最新备份和这本账
        不是同一本」（账本可能被整本换成了别的、或者空库）正是 I1 要抓的，结论却是一句全部成立"""
        self.must.append((code, title, [], why))

    def human(self, code: str, title: str, hits: list[str]) -> None:
        if hits:
            self.review.append((code, title, hits))

    def note(self, line: str) -> None:
        self.info.append(line)

    @property
    def failed(self) -> bool:
        return any(hits for _, _, hits, _ in self.must)

    @property
    def skipped(self) -> list[str]:
        return [code for code, _, _, why in self.must if why is not None]

    def print(self, head: list[str], show_all: bool = False) -> None:
        for line in head:
            print(line)
        bad = [m for m in self.must if m[2]]
        skipped = self.skipped
        summary = (f"{len(bad)} 项没过" if bad
                   else f"{len(self.must) - len(skipped)} 项通过" if skipped else "全部通过")
        print(f"\n【必须修】{summary}" + (f"、{len(skipped)} 项没比" if skipped else ""))
        for code, title, hits, why in self.must:
            if why is not None:
                print(f"  没比  {code} {title}（{why}）")
                continue
            print(f"  {'没过' if hits else '通过'}  {code} {title}" + (f"（{len(hits)} 处）" if hits else ""))
            _samples(hits, show_all, "")
        print(f"\n【要人核对】{'没有' if not self.review else f'{len(self.review)} 项'}（只列出来，是不是问题要人来定）")
        for code, title, hits in self.review:
            print(f"  {code} {title}（{len(hits)} 处）")
            # 按时间排的那几项（C1 C2 E1 E2 G1）都是新的在前：老的那几条多半早就看过了，
            # 一直占着样本位的话，最近那张新冒出来的只剩一个计数
            _samples(hits, show_all, "更早的")
        print("\n【仅供参考】（已经定过或还挂着的事、环境数字 —— 不算命中）")
        for line in self.info:
            print(f"  · {line}")
        if self.failed:
            end = "有「必须修」没过 —— 先别出账，找维护的人看一下（退出码 1）。"
        elif skipped:
            end = f"查过的恒等式都成立，但 {'、'.join(skipped)} 没比 —— 原因见上（退出码 0）。"
        else:
            end = "账本的恒等式全部成立（退出码 0）。"
        print("\n结论：" + end)


def _samples(hits: list[str], show_all: bool, older: str) -> None:
    shown = hits if show_all else hits[:SAMPLES]
    for h in shown:
        print(f"          {h}")
    if len(hits) > len(shown):
        print(f"          …… {older}还有 {len(hits) - len(shown)} 处（--all 全部列出）")


def _jst(ts: str) -> dt.datetime:
    """库里 naive UTC 的时刻 → 日本时间。不从 tools.restore 借：那边一 import 就连上了 app.db，
    而这里在拍快照之前一个 app 模块都不许 import"""
    return dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc).astimezone(JST)


def _yen(n: int | None) -> str:
    return "—" if n is None else f"¥{n:,}"


def _mb(n: int) -> str:
    mb = n / 1024 / 1024
    # 盘的剩余空间动辄几 TB，写成「5721434.4 MB」没人一眼看得懂
    return f"{mb / 1024:.1f} GB" if mb >= 10 * 1024 else f"{mb:.1f} MB"


def _json(text: str | None) -> dict[str, Any]:
    """JSON 列：SQL 的 NULL 和 JSON 的 null（SQLAlchemy 把 Python 的 None 存成后者）都当空"""
    return (json.loads(text) if text else None) or {}


def _in_post(on: str, member: sqlite3.Row) -> bool:
    """那一天在不在籍（日期都是 ISO 字符串，直接比）"""
    return member["joined_on"] <= on and (member["left_on"] is None or on <= member["left_on"])


def _snapshot(src: Path, into: Path) -> Path:
    """只读打开、VACUUM INTO 一份。src 不在的话 mode=ro 不会替它建一个空库"""
    if not src.is_file():
        sys.exit(f"账本不在：{src}（换个路径：NAGAYA_DB=… 或 --file=…）")
    snap = into / "snapshot.db"
    con = None
    try:
        con = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
        con.execute("VACUUM INTO ?", (str(snap),))
    except sqlite3.Error as e:
        sys.exit(_snapshot_failed(e))
    finally:
        if con is not None:
            con.close()
    return snap


def _snapshot_failed(e: sqlite3.Error) -> str:
    """拍不了快照时说什么。**只有文件本身坏了才提 tools.restore** —— 那是最险的一步手工操作，
    锁着、权限不对、WAL 库缺了 -wal/-shm（这台的 SQLite 只读时不替它建）都说明不了账本坏了，
    照着去恢复就是拿备份盖掉一本好账。和 restore._in_use 一样按错误码分"""
    code = getattr(e, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return f"账本文件坏了（{e}），连快照都拍不了 —— 这本身就是要修的事：试试 tools.restore"
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return f"账本正被别的进程锁着（{e}），这次没体检 —— 多半是别的维护工具正在用它，过一会儿再试"
    if code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_PERM, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_AUTH):
        return (f"账本打不开（{e}）：权限不够，或者这是开着 WAL 的库却没带上它的 -wal / -shm。"
                "这次没体检，账本好坏不知道 —— 这不是该去恢复的理由")
    return f"拍快照失败（{e}），这次没体检，账本好坏不知道 —— 先别照这句去恢复"


def run(live: Path, from_file: bool) -> Report:
    """live：要体检的那个库文件（活账本或 --file 给的备份）。只读它一次（拍快照），之后全在快照上"""
    tmp = Path(tempfile.mkdtemp(prefix="nagaya-checkup-"))
    try:
        t0 = time.perf_counter()
        snap = _snapshot(live, tmp)
        took = (time.perf_counter() - t0) * 1000
        # **import app 之前**指到快照：app.db 在 import 那一刻就按它建连接
        os.environ["NAGAYA_DB"] = str(snap)
        return _checks(live, snap, from_file, took)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _checks(live: Path, snap: Path, from_file: bool, took_ms: float) -> Report:
    from sqlmodel import Session, select

    from app import migrate
    from app.db import engine
    from app.models import Statement
    from app.services import backup as backup_svc
    from app.services import bill as bill_svc
    from app.services import settings as settings_svc

    # build_bill 遇到账不平时会往日志里写一句「是哪几笔」—— 报告里 B1 已经点名了，别在终端上再刷一遍
    logging.getLogger("nagaya").setLevel(logging.CRITICAL)
    rep = Report()
    rep.note(f"快照用了 {took_ms:.0f} ms，之后全在快照上查（活库一个字节没动）")
    db = sqlite3.connect(snap)
    db.row_factory = sqlite3.Row
    q = lambda sql, *p: db.execute(sql, p).fetchall()  # noqa: E731

    try:
        # ------------------------------------------------------------ A 结构
        try:
            have = q("select version_num from alembic_version")
            ver = have[0][0] if have else None
        except sqlite3.OperationalError:
            ver = None
        head = migrate.head()
        rep.p0("A1", "表结构版本和代码一致", [] if ver == head else [f"库里是 {ver}，代码是 {head}"])
        rep.p0("A2", "integrity_check", [r[0] for r in q("pragma integrity_check") if r[0] != "ok"])
        rep.p0("A3", "外键都指得到", [
            f"{r[0]} 第 {r[1]} 行 → {r[2]}" for r in q("pragma foreign_key_check")
        ])
        rep.p0("A4", "库里有模型要的每一张表、每一列", migrate.drift(engine))

        # ------------------------------------------------------------ B 钱
        b1 = {r[0] for r in db.execute(backup_svc.SHARES_SQL)}
        rows = {r["id"]: r for r in q(
            "select e.id, e.kind, e.amount_jpy, e.deleted_at, coalesce(sum(s.amount_jpy), 0) shares "
            "from entry e left join entry_share s on s.entry_id = e.id group by e.id"
        )} if b1 else {}
        rep.p0("B1", "每一笔的分摊合计 = 金额（含软删的：撤销删除会把它带回来）", [
            f"#{i}  金额 {_yen(rows[i]['amount_jpy'])}  分摊合计 {_yen(rows[i]['shares'])}"
            + ("（已删）" if rows[i]["deleted_at"] else "")
            for i in sorted(b1)
        ])
        total = db.execute(backup_svc.BALANCE_SQL).fetchone()[0]
        rep.p0("B2", "每人余额加起来是 0", [f"合计是 {_yen(total)}"] if total else [])
        rep.p0("B3", "金额的正负和类型对得上", [
            f"#{r['id']}  {r['kind']}  {_yen(r['amount_jpy'])}" for r in q(
                "select id, kind, amount_jpy from entry where "
                "(kind = 'expense' and amount_jpy <= 0) or (kind = 'income' and amount_jpy >= 0) or "
                "(kind = 'settlement' and (amount_jpy <= 0 or to_member_id is null or to_member_id = payer_id)) "
                "or kind not in ('expense', 'income', 'settlement')"
            )
        ])
        rep.p0("B4", "转账的分摊只有一行、全额记在转入人头上", [
            f"#{r[0]}" for r in db.execute(backup_svc.SETTLEMENT_SQL)
        ])

        # ------------------------------------------------------------ 共用的几样
        members = {r["id"]: r for r in q("select * from member")}
        name = lambda mid: members[mid]["display_name"] if mid in members else f"#{mid}"  # noqa: E731
        monthly = {r["id"]: r["name"] for r in q("select id, name from category where monthly = 1")}
        cats = {r["id"]: r["name"] for r in q("select id, name from category")}
        entries = q("select * from entry order by id")
        shares: dict[int, dict[int, int]] = defaultdict(dict)
        for r in q("select entry_id, member_id, amount_jpy from entry_share"):
            shares[r[0]][r[1]] = r[2]
        audits: dict[int, list[tuple[str, str, dict | None]]] = defaultdict(list)
        for r in q("select target_id, action, at, after_json from audit_log "
                   "where target_table = 'entry' and action in ('create', 'update', 'restore', 'delete') "
                   "order by id"):
            audits[r[0]].append((r[1], r[2], _json(r[3]) or None))
        statements = {r["id"]: r for r in q("select id, cut_at, snapshot_json from statement")}
        balance: dict[int, int] = defaultdict(int)
        for e in entries:
            if e["deleted_at"] is None:
                balance[e["payer_id"]] += e["amount_jpy"]
                for m, v in shares[e["id"]].items():
                    balance[m] -= v

        # ------------------------------------------------------------ B7 / D1 账单
        st_bad: list[str] = []
        edited: list[str] = []
        for r in statements.values():
            snapm = _json(r["snapshot_json"]).get("members", [])
            if sum(m["closing"] for m in snapm):
                st_bad.append(f"第 {r['id']} 张的冻结快照：每人结余加起来是 {_yen(sum(m['closing'] for m in snapm))}")
        with Session(engine) as session:
            for st in session.exec(select(Statement).order_by(Statement.cut_at)):
                try:
                    b = bill_svc.build_bill(session, st)
                except Exception as e:  # noqa: BLE001 —— 账不平时 build_bill 抛 SettleError：记下来接着查
                    st_bad.append(f"第 {st.id} 张算不出来（{type(e).__name__}: {e}）—— 账单页会 500")
                    continue
                if b["edited_after_cut"]:
                    edited.append(f"#{st.id}")
            try:
                bill_svc.build_bill(session, None)
            except Exception as e:  # noqa: BLE001
                st_bad.append(f"草稿算不出来（{type(e).__name__}: {e}）—— 账单页会 500")
            simplify = settings_svc.get(session, "simplify_debts")
            remainder = settings_svc.get(session, "remainder_to")
            try:
                bdir = backup_svc.backup_dir(session)
            except ValueError:
                bdir = None
            every = settings_svc.get(session, "backup_every_hours")
        engine.dispose()
        rep.p0("B7", "每张账单都算得出来、冻结的每人结余加起来是 0", st_bad)
        rep.p0("D1", "账单编号的先后和出账时刻的先后一致（时钟被往回调过的话上期结转会算错）", [
            f"第 {r[0]} 张（{_jst(r[1]):%Y-%m-%d %H:%M}）晚于第 {r[2]} 张（{_jst(r[3]):%Y-%m-%d %H:%M}）编号，"
            "出账时刻却不晚于它（日本时间）" for r in q(
                "select b.id, b.cut_at, a.id, a.cut_at from statement a join statement b "
                "on b.id > a.id and b.cut_at <= a.cut_at"
            )
        ])

        # ------------------------------------------------------------ G2 留痕
        # 出账只动 statement_id、version（和固定费的日期，D30），这三样不比
        silent: list[str] = []
        no_audit: list[str] = []
        for e in entries:
            trail = audits.get(e["id"])
            if not trail:
                no_audit.append(f"#{e['id']}  {e['date']}  {_yen(e['amount_jpy'])}  {e['title'] or '—'}")
                continue
            act, _, after = trail[-1]
            if act == "delete":
                if e["deleted_at"] is None:
                    silent.append(f"#{e['id']}  最后一条审计是删除，行却还在")
                continue
            if e["deleted_at"] is not None:
                silent.append(f"#{e['id']}  行被删了，却没有删除的审计")
                continue
            after = after or {}
            diffs = [k for k in ("kind", "amount_jpy", "payer_id", "to_member_id", "category_id", "title", "note")
                     if after.get(k) != e[k]]
            if after.get("date") != e["date"] and not (e["category_id"] in monthly and e["statement_id"]):
                diffs.append("date")
            if after.get("shares") != {str(k): v for k, v in shares[e["id"]].items()}:
                diffs.append("shares")
            if diffs:
                silent.append(f"#{e['id']}  和最后一条审计对不上：{', '.join(diffs)}")
        rep.p0("G2", "库里每一笔都和它最后一条审计一致（对不上 ＝ 有人绕过 app 直接改了库）", silent)

        # ------------------------------------------------------------ I1 备份
        if from_file:
            rep.note("I1 没比：体检的就是一份备份文件")
        else:
            _i1(rep, q, bdir)

        # ------------------------------------------------------------ 要人核对
        # C1/C2 判在籍要用**业务日期**：固定费出账时日期被盖成出账日（D30），
        # 拿盖过的日子去判，「搬走前交的最后一个月房租、出账在搬走之后」全成了误报
        orig = _original_dates(q, statements, audits, monthly)
        c1, c2 = [], []
        for e in entries:
            if e["deleted_at"] is not None or e["kind"] == "settlement":
                continue
            on = orig.get(e["id"], e["date"])
            payer = members.get(e["payer_id"])
            if payer is not None and not _in_post(on, payer):
                c1.append(f"#{e['id']}  {on}  {_yen(e['amount_jpy'])}  {e['title'] or cats.get(e['category_id'], '—')}"
                          f"  付款人 {name(e['payer_id'])}（{payer['joined_on']} 〜 {payer['left_on'] or ''}）")
            for mid, v in shares[e["id"]].items():
                m = members.get(mid)
                if v and m is not None and not _in_post(on, m):
                    c2.append(f"#{e['id']}  {on}  {e['title'] or cats.get(e['category_id'], '—')}"
                              f"  {name(mid)} 担 {_yen(v)}（在籍 {m['joined_on']} 〜 {m['left_on'] or ''}）")
        # 要人核对的几张单子一律新的在前（理由见 Report.print）
        rep.human("C1", "付款人在那天不在籍（日期按记账时的，不按出账时盖的）", c1[::-1])
        rep.human("C2", "有人在不在籍的日子被摊了钱", c2[::-1])
        today = dt.datetime.now(backup_svc.JST).date().isoformat()
        rep.human("C3", "已经搬走的人余额不是 0（欠着钱走了，或者别人还欠他）", [
            f"{m['display_name']}（{m['left_on']} 搬走）  余额 {_yen(balance.get(mid, 0))}"
            for mid, m in members.items() if m["left_on"] is not None and m["left_on"] < today and balance.get(mid, 0)
        ])
        rep.human("E1", f"疑似漏填的固定费（前 {E1_WINDOW} 张里至少 {E1_MIN_HITS} 张都有，这张没有）",
                  _e1(statements, entries, monthly))
        rep.human("E2", "同一张账单（或草稿）里同一项固定费不止一笔", [
            f"{'草稿' if r['sid'] is None else f'第 {r[0]} 张'}  {monthly[r['cid']]}  {r['n']} 笔：{r['amounts']}"
            for r in q(
                "select statement_id sid, category_id cid, count(*) n, group_concat(amount_jpy, ' / ') amounts "
                "from entry where deleted_at is null and kind = 'expense' "
                "and category_id in (select id from category where monthly = 1) "
                "group by statement_id, category_id having count(*) > 1 "
                # 草稿最前，再从最新那张往前
                "order by statement_id is not null, statement_id desc, category_id"
            )
        ])
        rep.human("G1", "没有任何审计的账（不是经由 app 记进来的）", no_audit[::-1])

        # ------------------------------------------------------------ 仅供参考
        if edited:
            rep.note(f"出账后被改过的账单 {len(edited)} 张：{', '.join(edited[:20])}（账单页上各自标着，钱算得对）")
        if remainder == "rotate":
            rep.note("余数归谁 ＝ 逐笔轮转：权重 0 的人也占轮转位（还挂着的那条）")
        rep.note(f"转账方案：{'最少转账' if simplify else '按原始债权'}")
        _env(rep, live, bdir, every, from_file)
    finally:
        db.close()
    return rep


def _original_dates(q, statements, audits, monthly) -> dict[int, str]:  # noqa: ANN001
    """出账时被盖过日期的那几笔固定费，原来是哪天。

    出账那条审计里记着 stamped {账目 id: 原日期}；更早出的账单没这个键，就退回
    「出账之前最后一条审计里写的日期」。只管挂在固定费上、已经出过账的
    """
    out: dict[int, str] = {}
    known: set[int] = set()
    for r in q("select target_id, after_json from audit_log where action = 'cut_statement' "
               "and target_table = 'statement'"):
        after = _json(r[1])
        if "stamped" in after:
            known.add(r[0])
            out.update({int(k): v for k, v in after["stamped"].items()})
    for e in q("select id, statement_id, category_id from entry where statement_id is not null"):
        if e["category_id"] not in monthly or e["statement_id"] in known or e["id"] in out:
            continue
        cut = statements[e["statement_id"]]["cut_at"]
        before = [a for _, at, a in audits.get(e["id"], []) if a and at <= cut]
        if before and before[-1].get("date"):
            out[e["id"]] = before[-1]["date"]
    return out


def _e1(statements, entries, monthly) -> list[str]:  # noqa: ANN001
    """结了固定费的账单按时间排，每一张往前看 E1_WINDOW 张。只看出账那一刻在面板上的项（快照 monthly_ids）。
    新的那张在前"""
    full = []
    for r in sorted(statements.values(), key=lambda r: r["cut_at"]):
        snap = _json(r["snapshot_json"])
        if snap.get("include_monthly", True) is not False:
            full.append((r, snap))
    present: dict[int, set[int]] = defaultdict(set)
    for e in entries:
        if e["deleted_at"] is None and e["kind"] == "expense" and e["statement_id"] and e["category_id"] in monthly:
            present[e["statement_id"]].add(e["category_id"])
    out = []
    for i in range(len(full) - 1, E1_WINDOW - 1, -1):
        st, snap = full[i]
        on_panel = set(snap["monthly_ids"]) if "monthly_ids" in snap else set(monthly)
        for cid in sorted(on_panel & set(monthly)):
            hits = sum(cid in present[w["id"]] for w, _ in full[i - E1_WINDOW:i])
            if hits >= E1_MIN_HITS and cid not in present[st["id"]]:
                # 日期按日本时间：早上 9 点前出的账按 UTC 截是前一天，和 app 里「M/D 出账」对不上
                out.append(f"第 {st['id']} 张（{_jst(st['cut_at']):%Y-%m-%d}）的 {monthly[cid]}："
                           f"前 {E1_WINDOW} 张有 {hits} 张记了，这张按 ¥0 出的")
    return out


def _i1(rep: Report, q, bdir: Path | None) -> None:  # noqa: ANN001
    """最新那份备份里有、活库里没了的行。这几张表 app 从不硬删（备忘会，不在内）。

    比 id 集合、不比条数：删掉三笔又新记三笔，条数一样，丢的照样丢了。
    **先认是不是同一本账**：备份目录里放着另一本账的备份（种子库、别的屋）时，
    按 id 比出来的「少了 N 行」是一句假话。可「不是同一本」本身就要人看：
    卷没挂上、放错了文件，活账本被整本换掉时正是这个样子 —— 印「没比」，再进「要人核对」。
    目录不在、一份备份都还没有（刚装好）只印「没比」
    """
    title = "最新备份里有的行活库里都还在"
    if bdir is None or not bdir.is_dir():
        rep.skip("I1", title, f"备份目录不在：{bdir}")
        return
    from app.services.backup import NAME_RE

    files = sorted(p for p in bdir.iterdir() if NAME_RE.match(p.name))
    if not files:
        rep.skip("I1", title, f"备份目录里一份都没有：{bdir}")
        return
    newest = files[-1]
    lost: list[str] = []
    try:
        bk = sqlite3.connect(f"{newest.resolve().as_uri()}?mode=ro", uri=True)
        try:
            theirs = dict(bk.execute("select id, created_at from member"))
            ours = {r[0]: r[1] for r in q("select id, created_at from member")}
            if theirs and not ours:
                why = f"活账本里一个成员都没有，最新那份备份（{newest.name}）里有 {len(theirs)} 个"
                rep.skip("I1", title, why)
                rep.human("I1", "活账本像是被换成了空库（卷没挂上 / 放错了文件？）", [why])
                return
            if any(ours.get(i) != c for i, c in theirs.items()):
                why = f"最新那份备份（{newest.name}）和这本账不是同一本（成员建档时刻对不上）"
                rep.skip("I1", title, why)
                rep.human("I1", "最新备份和这本账不是同一本 —— 账本可能被整本换过（卷没挂上 / 放错文件），"
                                "也可能是备份目录里混进了别的账", [why])
                return
            for table in ("entry", "statement", "audit_log", "member", "category"):
                gone = {r[0] for r in bk.execute(f"select id from {table}")} - {r[0] for r in q(f"select id from {table}")}
                if gone:
                    lost.append(f"{table}：{len(gone)} 行，例如 id {sorted(gone)[:10]}")
        finally:
            bk.close()
    except sqlite3.Error as e:
        why = f"最新那份备份打不开（{newest.name}：{e}）"
        rep.skip("I1", title, why)
        rep.human("I1", "最新那份备份打不开", [why])
        return
    if lost:
        lost.append(f"（对照的是 {newest.name}。刚做过恢复的话，这正是被退回去的那些 —— 核对要不要补记，"
                    "data/replaced-* 里有恢复前的旧账本）")
    rep.p0("I1", title, lost)


def _env(rep: Report, live: Path, bdir: Path | None, every: Any, from_file: bool) -> None:
    """盘、备份目录、留下来的旧副本。**同盘和剩余空间按活库的真实路径量**，
    不借 backup.status()：在快照会话上调它，量到的是临时目录里那份快照所在的盘"""
    size = sum(p.stat().st_size for p in (live, Path(f"{live}-wal")) if p.exists())
    rep.note(f"账本 {_mb(size)}（含 -wal），所在的盘剩 {_mb(shutil.disk_usage(live.parent).free)}")
    if from_file:
        return
    if bdir is not None and bdir.is_dir():
        from app.services.backup import NAME_RE

        files = sorted(p for p in bdir.iterdir() if NAME_RE.match(p.name))
        same = os.stat(bdir).st_dev == os.stat(live).st_dev
        newest = files[-1].name if files else "一份都没有"
        rep.note(f"备份目录 {bdir}：{len(files)} 份，最新 {newest}，盘上剩 {_mb(shutil.disk_usage(bdir).free)}"
                 + ("；和账本同一块盘（挡不住盘坏，默认就是这样）" if same else ""))
    else:
        rep.note(f"备份目录用不了：{bdir}")
    if not every:
        rep.note("自动备份关着（backup_every_hours = 0）")
    stale = [p for pattern in ("before-migrate-*.db", "replaced-*", "*.part") for p in live.parent.glob(pattern)]
    if stale:
        rep.note(f"data/ 里留着 {len(stale)} 份旧副本（升级前快照 / 恢复时挪走的旧账本 / 半截文件）："
                 + ", ".join(p.name for p in stale[:6]) + "，确认不用了可以手动删")
    secret = os.getenv("NAGAYA_SECRET")
    if secret and len(secret.encode()) < MIN_SECRET_BYTES:
        rep.note(f"这个终端里的 NAGAYA_SECRET 只有 {len(secret.encode())} 字节（服务那边的环境要另看）")


def _args(argv: list[str]) -> tuple[str | None, bool] | None:
    """(--file 给的路径, --all)。认不出的参数一律 None —— 原来只认 `--file=`，
    顺手写成 `--file 备份.db` 的话那个路径被悄悄扔掉，体检的是活账本、照样印一份干净的报告，
    人却以为查的是那份备份（恢复之前正是这么用的）"""
    given: str | None = None
    show_all = False
    rest = iter(argv)
    for a in rest:
        if a.startswith("--file=") and len(a) > len("--file=") and given is None:
            given = a[len("--file="):]
        elif a == "--file" and given is None:
            given = next(rest, None)
            if not given or given.startswith("--"):
                return None
        elif a == "--all":
            show_all = True
        else:
            return None
    return given, show_all


def main(argv: list[str]) -> int:
    args = _args(argv)
    if args is None:
        print(USAGE, file=sys.stderr)
        return 2
    given, show_all = args
    if given:
        live, from_file = Path(given).expanduser().resolve(), True
    else:
        # 和 app.db 同一个默认值；**不 import app.db**：它一 import 就按 NAGAYA_DB 建连接，
        # 而那一刻还没拍快照
        live = Path(os.getenv("NAGAYA_DB", BACKEND / "data" / "nagaya.db")).resolve()
        from_file = False
    rep = run(live, from_file)
    stamp = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    rep.print([f"nagaya 体检  {stamp}（日本时间）", f"{'备份文件' if from_file else '账本'}：{live}"], show_all)
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
