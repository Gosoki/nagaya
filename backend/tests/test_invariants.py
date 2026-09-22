"""随机操作序列下的恒等式 —— 这是整个账本最后一道防线。

单点用例只能证明「我想到的那几种情况是对的」。这里换个问法：
**随便怎么折腾，钱都不许多也不许少。**

每一步之后都断言两条：
    Σ(每人已垫付) − Σ(每人应担) ≡ 0
    每一笔账的 Σshares ≡ amount
操作池里放的是真实会发生的事：记账（含自定义权重和调整额）、改金额/日期/分类/付款人、
删、恢复、出账、转账、成员搬走、成员搬回来、**中途备份**。

跑完再逐张检查每张已出账单和当前草稿的 Σclosing ≡ 0 —— 展示层也不许把钱算丢。

备份那一支单独说一句：**每一份中途产出的备份自己也要满足同样两条**。
备份是在账本一直被写的过程中取的快照，「取的那一刻恰好是半截状态」这件事
只有这么撞才撞得出来。
"""

from __future__ import annotations

import datetime as dt
import random
import sqlite3
from pathlib import Path

from sqlmodel import Session, select

from app.core.rules import RuleError
from app.core.split import SplitError
from app.models import Category, Entry, EntryKind, EntryShare, Member, Statement
from app.services import backup as backup_svc
from app.services import ledger
from app.services.bill import BillError, build_bill, cut_statement

#: 10 条序列 × 100 步，约 6 秒。红了的话报错信息里带着 seed 和 step，原地就能复现
SEEDS = range(1, 11)
STEPS = 100


def _check(session: Session, tag: str) -> None:
    paid: dict[int, int] = {}
    owed: dict[int, int] = {}
    for e in session.exec(select(Entry).where(Entry.deleted_at.is_(None))):
        paid[e.payer_id] = paid.get(e.payer_id, 0) + e.amount_jpy
    rows = session.exec(
        select(EntryShare)
        .join(Entry, Entry.id == EntryShare.entry_id)
        .where(Entry.deleted_at.is_(None))
    )
    for s in rows:
        owed[s.member_id] = owed.get(s.member_id, 0) + s.amount_jpy
    ids = [m.id for m in session.exec(select(Member))]
    total = sum(paid.get(i, 0) - owed.get(i, 0) for i in ids)
    assert total == 0, f"{tag}：Σ余额 = {total} ≠ 0"

    for e in session.exec(select(Entry).where(Entry.deleted_at.is_(None))):
        got = sum(
            s.amount_jpy for s in session.exec(select(EntryShare).where(EntryShare.entry_id == e.id))
        )
        assert got == e.amount_jpy, f"{tag}：账目 {e.id} 的 Σshares {got} ≠ 金额 {e.amount_jpy}"


def _check_backup(path: Path, tag: str) -> None:
    """备份是**在账本一直被写的过程中**取的快照，所以它自己也得满足那两条。"""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert list(con.execute("PRAGMA integrity_check"))[0][0] == "ok", f"{tag}：备份打不开"
        paid = dict(
            con.execute(
                "select payer_id, sum(amount_jpy) from entry where deleted_at is null group by payer_id"
            )
        )
        owed = dict(
            con.execute(
                "select s.member_id, sum(s.amount_jpy) from entry_share s "
                "join entry e on e.id = s.entry_id where e.deleted_at is null group by s.member_id"
            )
        )
        ids = [r[0] for r in con.execute("select id from member")]
        total = sum(paid.get(i, 0) - owed.get(i, 0) for i in ids)
        assert total == 0, f"{tag}：备份里的 Σ余额 = {total}"
        bad = len(
            list(
                con.execute(
                    "select e.id from entry e left join entry_share s on s.entry_id = e.id "
                    "where e.deleted_at is null group by e.id "
                    "having coalesce(sum(s.amount_jpy), 0) <> e.amount_jpy"
                )
            )
        )
        assert bad == 0, f"{tag}：备份里有 {bad} 笔 Σshares ≠ amount"
    finally:
        con.close()


def _setup(session: Session, members: list[Member]) -> tuple[list[int], list[int]]:
    cats = [Category(name=f"c{i}", monthly=(i == 0), display_order=i) for i in range(3)]
    for c in cats:
        session.add(c)
    session.commit()
    for c in cats:
        session.refresh(c)
    return [m.id for m in members], [c.id for c in cats]


def _one_run(session: Session, members: list[Member], seed: int) -> None:
    rng = random.Random(seed)
    mid, cid = _setup(session, members)
    seen: list[int] = []

    for step in range(STEPS):
        op = rng.choices(
            ["create", "update", "delete", "restore", "cut", "settle", "leave", "join", "backup"],
            weights=[34, 22, 10, 6, 8, 14, 3, 3, 8],
        )[0]
        try:
            if op == "create":
                kind = rng.choices([EntryKind.expense, EntryKind.income], [9, 1])[0]
                amount = rng.randint(1, 300_000) * (1 if kind == EntryKind.expense else -1)
                rule = None
                if rng.random() < 0.45:
                    weights = {str(i): rng.randint(0, 4) for i in mid}
                    if sum(weights.values()) == 0:
                        weights[str(rng.choice(mid))] = 1
                    rule = {"mode": "ratio", "weights": weights}
                    if rng.random() < 0.4:
                        rule["adjustments"] = {str(rng.choice(mid)): rng.randint(-5_000, 5_000)}
                e = ledger.create_entry(
                    session, actor_id=mid[0], kind=kind,
                    on=dt.date(2026, rng.randint(1, 9), rng.randint(1, 28)),
                    amount=amount, payer_id=rng.choice(mid),
                    category_id=rng.choice(cid), rule=rule,
                )
                seen.append(e.id)
            elif op == "settle":
                a, b = rng.sample(mid, 2)
                e = ledger.create_entry(
                    session, actor_id=mid[0], kind=EntryKind.settlement,
                    on=dt.date(2026, rng.randint(1, 9), rng.randint(1, 28)),
                    amount=rng.randint(1, 200_000), payer_id=a, to_member_id=b,
                )
                seen.append(e.id)
            elif op == "update" and seen:
                e = session.get(Entry, rng.choice(seen))
                if e is not None and e.deleted_at is None:
                    fields: dict = {}
                    if rng.random() < 0.6:
                        fields["amount_jpy"] = (
                            rng.randint(1, 300_000) if e.kind != EntryKind.income
                            else -rng.randint(1, 300_000)
                        )
                    if rng.random() < 0.3:
                        fields["date"] = dt.date(2026, rng.randint(1, 9), rng.randint(1, 28))
                    if rng.random() < 0.25 and e.kind != EntryKind.settlement:
                        fields["category_id"] = rng.choice(cid)
                    if rng.random() < 0.2:
                        fields["payer_id"] = rng.choice(mid)
                    if fields:
                        ledger.update_entry(session, e, actor_id=mid[0], version=e.version, fields=fields)
            elif op == "delete" and seen:
                e = session.get(Entry, rng.choice(seen))
                if e is not None and e.deleted_at is None:
                    ledger.delete_entry(session, e, actor_id=mid[0])
            elif op == "restore" and seen:
                e = session.get(Entry, rng.choice(seen))
                if e is not None and e.deleted_at is not None:
                    ledger.restore_entry(session, e, actor_id=mid[0])
            elif op == "cut":
                cut_statement(session, actor_id=mid[0])
            elif op == "leave":
                m = session.get(Member, rng.choice(mid))
                still_in = sum(1 for i in mid if session.get(Member, i).left_on is None)
                if m.left_on is None and still_in > 2:
                    m.left_on = dt.date(2026, rng.randint(5, 9), 15)
                    session.add(m)
                    session.commit()
            elif op == "backup":
                made = backup_svc.run(session)
                _check_backup(Path(made["path"]), f"seed={seed} step={step}")
            elif op == "join":
                m = session.get(Member, rng.choice(mid))
                if m.left_on is not None:
                    m.left_on = None
                    session.add(m)
                    session.commit()
        except (ledger.LedgerError, BillError, RuleError, SplitError):
            # 被正确拒绝的操作也是一种结果，回滚之后继续 —— 拒绝之后账本同样不许坏
            session.rollback()

        _check(session, f"seed={seed} step={step} op={op}")

    # 展示层也要守恒：每张账单上「各人结余」加起来必须是 0
    for st in session.exec(select(Statement)):
        bill = build_bill(session, st)
        assert sum(r["closing"] for r in bill["members"]) == 0, f"账单 {st.id} 的 Σclosing ≠ 0"
    draft = build_bill(session, None)
    assert sum(r["closing"] for r in draft["members"]) == 0, "草稿账单的 Σclosing ≠ 0"


def test_invariants_hold_under_random_operations(session: Session, members) -> None:
    for seed in SEEDS:
        # 每条序列都从同一个干净库开始：把上一轮造的东西清掉
        for table in (EntryShare, Entry, Statement, Category):
            session.exec(table.__table__.delete())  # type: ignore[call-overload]
        for m in members:
            m.left_on = None
            session.add(m)
        session.commit()
        _one_run(session, members, seed)
