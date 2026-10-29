"""进程里那几样「没人看着也得一直对」的事：后台备份循环、空闲时归还内存、落盘强度、签名密钥。

它们都不碰钱，坏了也不报错 —— 正因为这样才要钉住：坏的那一天没人会发现。
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from app import auth, main, middleware
from app.db import engine
from app.models import Category, EntryKind, Member
from app.services import ledger
from app.services.settings import seed_settings


def test_the_backup_loop_survives_a_failing_memory_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """release_memory 原来在 try 外面：它抛一次（MemoryError、起不了线程），整个循环就退出了，
    自动备份从此停摆 —— task 只在关机时才被看一眼，一行日志都不留。"""
    calls = {"backup": 0, "release": 0}

    def once() -> None:
        calls["backup"] += 1

    def release() -> None:
        calls["release"] += 1
        if calls["release"] == 1:
            raise RuntimeError("simulated: release_memory failed once")

    monkeypatch.setattr(main, "_backup_once", once)
    monkeypatch.setattr(main, "release_memory", release)
    monkeypatch.setattr(main, "_BACKUP_TICK", 0)

    async def drive() -> bool:
        task = asyncio.create_task(main._daily_backup())
        for _ in range(300):
            await asyncio.sleep(0.01)
            if calls["backup"] >= 3 or task.done():
                break
        died = task.done()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError):
            pass
        return died

    assert asyncio.run(drive()) is False, "循环自己退出了 —— 自动备份停摆"
    assert calls["backup"] >= 3


def _file_engine(tmp_path):  # noqa: ANN001, ANN202
    eng = create_engine(f"sqlite:///{tmp_path}/x.db", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        seed_settings(s)
        m = Member(name="a", display_name="A", joined_on=dt.date(2026, 1, 1))
        c = Category(name="日用品")
        s.add_all([m, c])
        s.commit()
        for i in range(30):
            ledger.create_entry(s, actor_id=m.id, kind=EntryKind.expense, on=dt.date(2026, 9, 1),
                                amount=100 + i, payer_id=m.id, category_id=c.id)
    return eng


def test_idle_release_refreshes_the_planner_statistics(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """库里没有统计信息时，查询计划会去挑区分度很低的索引（entry.kind 九成九是支出）。
    空闲归还内存那一下顺手 PRAGMA optimize，统计就有了（sqlite_stat1）。"""
    eng = _file_engine(tmp_path)
    monkeypatch.setattr(middleware, "engine", eng)
    middleware.release_memory()
    with eng.connect() as c:
        stats = c.exec_driver_sql("select tbl, idx from sqlite_stat1").all()
    assert ("entry", "ix_entry_kind") in stats, stats


def test_a_failing_optimize_still_gives_the_memory_back(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """optimize 只关查询计划，它没做成不许拦着后面关连接、还内存，也不许把异常往外抛"""
    eng = _file_engine(tmp_path)
    disposed: list[bool] = []

    class Boom:
        def connect(self):  # noqa: ANN202
            raise RuntimeError("simulated: optimize failed")

        def dispose(self) -> None:
            disposed.append(True)

    monkeypatch.setattr(middleware, "engine", Boom())
    middleware.release_memory()
    assert disposed == [True]
    eng.dispose()


def test_commits_are_fsynced() -> None:
    """WAL + NORMAL 下，已经回了 201 的账在宿主机断电时可能悄悄回滚；FULL 每次提交落一次盘"""
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA synchronous").scalar() == 2      # 2 ＝ FULL
    probe = create_engine(f"sqlite:///{engine.url.database}", poolclass=NullPool)
    with probe.connect() as c:                                             # 别的引擎也一样（迁移用的那个）
        assert c.exec_driver_sql("PRAGMA synchronous").scalar() == 2
    probe.dispose()


def test_a_short_secret_from_the_environment_is_called_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """NAGAYA_SECRET 设成一个字符也照样签 token：拿到一张就能离线把密钥试出来。
    不拒绝启动（已经这么配着的那台一升级就起不来），日志里说一句"""
    said: list[str] = []

    class Log:
        def warning(self, msg: str, *args) -> None:  # noqa: ANN002
            said.append(msg % args)

    monkeypatch.setattr(auth, "log", Log())
    monkeypatch.setenv("NAGAYA_SECRET", "x")
    assert auth._load_secret() == "x"
    assert said and "NAGAYA_SECRET" in said[0]

    said.clear()
    monkeypatch.setenv("NAGAYA_SECRET", "k" * auth.MIN_SECRET_BYTES)
    auth._load_secret()
    assert not said
