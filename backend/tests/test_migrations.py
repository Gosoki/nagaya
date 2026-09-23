"""表结构迁移（Alembic）。D18：录真账之前切过来，从此加字段不再弄坏老库和老备份。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from app import migrate
from tools.restore import _upgraded_copy


def _version(path: Path) -> str | None:
    con = sqlite3.connect(path)
    try:
        return con.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        con.close()


def test_migrations_build_exactly_the_models(tmp_path: Path) -> None:
    """**改了模型就得写迁移。** 这一条在，漏写的那天测试就红。

    从空库一路升到最新，和模型逐表逐列逐索引比 —— 一处对不上都不行。
    怎么写迁移见 alembic/versions/README.md。
    """
    db = tmp_path / "fresh.db"
    assert migrate.upgrade(db) is None, "空库没东西可拍"
    assert _version(db) == migrate.head()
    with create_engine(f"sqlite:///{db}").connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}),
                                SQLModel.metadata)
    assert diff == [], f"模型和迁移对不上（是不是改了 models.py 没写迁移？）：{diff}"


def _legacy(tmp_path: Path) -> Path:
    """切 Alembic 之前的库：create_all 建的，没有 alembic_version"""
    db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    return db


def test_a_create_all_ledger_is_refused_with_a_reason(tmp_path: Path) -> None:
    """2026-09-23 把迁移合成了一份基线，旧格式的库不再接管。

    拒绝要说清为什么；不许先拍快照（反正升不了），也不许动它一个字节
    """
    db = _legacy(tmp_path)
    before = db.read_bytes()
    with pytest.raises(migrate.SchemaDrift, match="旧格式"):
        migrate.upgrade(db)
    assert db.read_bytes() == before
    assert not list(tmp_path.glob("before-migrate-*"))


def test_a_ledger_missing_columns_refuses_to_start(tmp_path: Path) -> None:
    """版本号对、却缺列的库 —— 别起来，说清楚缺了什么。起来了、查到那一列才 500 更糟"""
    db = tmp_path / "x.db"
    migrate.upgrade(db)
    con = sqlite3.connect(db)
    con.execute("alter table category drop column same_as_last")
    con.commit()
    con.close()
    with pytest.raises(migrate.SchemaDrift, match="category.same_as_last"):
        migrate.upgrade(db)


def test_restore_takes_a_current_backup_but_not_a_newer_or_legacy_one(tmp_path: Path) -> None:
    """现在这版的备份照装（升的是拷贝，原件不动）；更新的代码做的、切 Alembic 之前的，拦下"""
    ok = tmp_path / "ok.db"
    migrate.upgrade(ok)
    before = ok.read_bytes()
    ready = _upgraded_copy(ok)
    assert _version(ready) == migrate.head()
    assert ok.read_bytes() == before, "升的是拷贝，备份原件一个字节都不许动"
    assert not Path(str(ready) + "-wal").exists() or Path(str(ready) + "-wal").stat().st_size == 0, \
        "升级写的东西不许还躺在 -wal 里 —— 接下来只拷主文件"

    newer = tmp_path / "newer.db"
    migrate.upgrade(newer)
    con = sqlite3.connect(newer)
    con.execute("update alembic_version set version_num = 'ffff'")
    con.commit()
    con.close()
    with pytest.raises(Exception, match="ffff"):
        _upgraded_copy(newer)

    with pytest.raises(migrate.SchemaDrift, match="旧格式"):
        _upgraded_copy(_legacy(tmp_path))


def test_a_failing_upgrade_does_not_pile_up_snapshots(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """升级在这本账上失败 → 服务一遍遍重启（Docker 的 restart: unless-stopped 就会这样）。

    每次开机都先拍一整份的话，盘迟早写满。库没动过就只留一张；
    库比代码新（代码回滚了）根本升不了，一张都不拍
    """
    db = tmp_path / "x.db"
    migrate.upgrade(db)
    con = sqlite3.connect(db)
    con.execute("insert into bundle (title, created_at) values ('x', '2026-01-01 00:00:00')")
    con.commit()
    con.close()

    def boom(*_a, **_k) -> None:
        raise RuntimeError("迁移在这本账上失败")

    # 假装代码里多了一个 0002，而它在这本账上跑不过去
    monkeypatch.setattr(migrate, "head", lambda: "0002")
    monkeypatch.setattr(migrate.command, "upgrade", boom)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            migrate.upgrade(db)
    shots = list(tmp_path.glob("before-migrate-*"))
    assert len(shots) == 1 and shots[0].suffix == ".db" and shots[0].stat().st_size > 0
    monkeypatch.undo()

    newer = tmp_path / "sub" / "newer.db"
    newer.parent.mkdir()
    migrate.upgrade(newer)
    con = sqlite3.connect(newer)
    con.execute("update alembic_version set version_num = 'ffff'")
    con.commit()
    con.close()
    with pytest.raises(migrate.SchemaDrift, match="ffff"):
        migrate.upgrade(newer)
    assert not list(newer.parent.glob("before-migrate-*"))
