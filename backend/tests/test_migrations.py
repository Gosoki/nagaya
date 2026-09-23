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
    """D18 之前的库：create_all 建的，没有 alembic_version。再故意少一张表、少一个索引 ——
    create_all 只在建表时建索引，老库上后加的索引本来就是缺的"""
    db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(db)
    con.executescript("""
        drop table member_pref;
        drop index ix_entry_date;
        insert into member (name, display_name, color, display_order, joined_on, password_hash,
                            lang, avatar_version, created_at)
        values ('go', 'Go', '#3d4785', 0, '2026-01-01', '', 'zh', 0, '2026-01-01 00:00:00');
    """)
    con.commit()
    con.close()
    return db


def test_a_create_all_ledger_is_adopted_in_place(tmp_path: Path) -> None:
    """现在这本账本就是这样一个库：升上来只补缺的，数据一行不动，升之前先拍快照。"""
    db = _legacy(tmp_path)
    shot = migrate.upgrade(db)

    assert _version(db) == migrate.head()
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("select name from sqlite_master")}
    assert "member_pref" in names, "缺的表要补上"
    assert "ix_entry_date" in names, "缺的索引要补上"
    assert "ix_entry_deleted_at" not in names, "0002 去掉的索引不许留着"
    assert con.execute("select display_name from member").fetchall() == [("Go",)]
    con.close()

    assert shot and Path(shot).exists(), "真有要升的版本时，升之前得先留一份"
    con = sqlite3.connect(shot)
    assert con.execute("select count(*) from member").fetchone()[0] == 1
    con.close()

    assert migrate.upgrade(db) is None, "已经是最新的就什么都不做，也不再拍快照"


def test_a_ledger_older_than_the_baseline_refuses_to_start(tmp_path: Path) -> None:
    """缺列的库补不了 —— 那就别起来，说清楚缺了什么。起来了、查到那一列才 500 更糟"""
    db = _legacy(tmp_path)
    con = sqlite3.connect(db)
    con.execute("alter table category drop column same_as_last")
    con.commit()
    con.close()
    with pytest.raises(migrate.SchemaDrift, match="category.same_as_last"):
        migrate.upgrade(db)


def test_restore_upgrades_an_old_backup_but_not_a_newer_one(tmp_path: Path) -> None:
    """旧备份升上来再装（原件不动）；更新的代码做的备份认不出版本，拦下"""
    old = _legacy(tmp_path)
    before = old.read_bytes()
    ready = _upgraded_copy(old)
    assert _version(ready) == migrate.head()
    assert old.read_bytes() == before, "升的是拷贝，备份原件一个字节都不许动"
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
