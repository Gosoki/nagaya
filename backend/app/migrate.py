"""开机把库升到最新的表结构（Alembic）。

D18 定的是「录真账之前切 Alembic」，这就是那一步。之前一直是 create_all ——
它只会建缺的表，**不会给已有的表加列**，于是每加一个字段，老库一开就是
`no such column`，加字段之前做的备份也就恢复不回来了。

现在：改了模型就写一份迁移（alembic/versions/README.md 里有怎么写），
开机自动升；恢复一份旧备份时也先按同样的步骤升一遍（tools/restore.py）。
基线是 0001（2026-09-23 的整套表）。那之前 create_all 建的旧格式库不再接管。

三件事缺一不可：
  * **升之前先拍一张快照**（只在真有要升的版本时）：SQLite 的整表重建
    （改列要靠它）中途失败的话，库会停在半截，得有一份能退回去的；
  * **升的时候关掉外键**：整表重建要先删旧表再改名，外键开着的话，
    删一张被引用的表会连带清掉引用它的行，或者直接失败（Alembic 文档的原话）；
  * **升完核对**：库里的列和模型对不上就拒绝启动。比「起来了，查到那一列才 500」好。
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from app import models  # noqa: F401 —— 导入即注册全部表，核对要读 metadata

BASE = Path(__file__).resolve().parents[1]


class SchemaDrift(RuntimeError):
    """升完了，库和代码还是对不上。"""


def _config(conn=None) -> Config:  # noqa: ANN001
    cfg = Config(str(BASE / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE / "alembic"))
    if conn is not None:
        cfg.attributes["connection"] = conn
    return cfg


def head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head() or ""


def upgrade(path: Path, *, snapshot: bool = True) -> str | None:
    """把 `path` 这个库升到最新。返回升之前拍的快照路径（没拍就是 None）。

    `snapshot=False` 给恢复工具用：它升的是一份临时拷贝，出事了原件还在。
    """
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
            tables = inspect(conn).get_table_names()
            conn.rollback()
            shot = None
            if current is None and set(tables) - {"alembic_version"}:
                raise SchemaDrift(
                    "这是切 Alembic 之前的旧格式账本（2026-09-23 之前 create_all 建的，"
                    "库里没有表结构版本号），现在的代码不再接管它。"
                    "换一份 2026-09-23 之后做的备份，或者把代码切回那之前的版本。"
                )
            if current and current != head():
                _known(current)
            if current != head() and tables and snapshot:
                shot = _snapshot(conn, path, current)
            # PRAGMA foreign_keys 在事务里改不了，得在 begin 之前
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
            with conn.begin():
                command.upgrade(_config(conn), "head")
            bad = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            conn.rollback()
            if bad:
                raise SchemaDrift(f"升完之后有 {len(bad)} 行外键对不上，例如 {bad[:3]}")
        missing = drift(engine)
        if missing:
            raise SchemaDrift(
                "库里缺这些表/列：" + "、".join(missing)
                + " —— 这份库和它记着的表结构版本对不上，自动升不上来。"
                + "换一份新一点的备份，或者把代码切回做这份库时的版本。"
            )
        return shot
    finally:
        engine.dispose()


def drift(engine) -> list[str]:  # noqa: ANN001
    """模型里有、库里没有的表和列。多出来的不管（老代码留下的，不妨碍）"""
    insp = inspect(engine)
    have = set(insp.get_table_names())
    out: list[str] = []
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in have:
            out.append(table.name)
            continue
        cols = {c["name"] for c in insp.get_columns(table.name)}
        gone = [c.name for c in table.columns if c.name not in cols]
        if gone:
            out.append(f"{table.name}.{'/'.join(gone)}")
    return out


def _known(current: str) -> None:
    """库的版本号这份代码认不认识。不认识就是**更新的代码**升过它（代码回滚了）——
    升不了，也就不用先拍快照：先拍再报错的话，每重启一次就白拍一整份"""
    try:
        ScriptDirectory.from_config(_config()).get_revision(current)
    except Exception as e:  # noqa: BLE001 —— Alembic 认不出版本时抛的类型随版本变
        raise SchemaDrift(
            f"库的表结构版本是 {current}，这份代码不认识 —— 它是更新的代码升过的。"
            "把代码切回新版，或者恢复一份这个版本之前的备份。"
        ) from e


def _snapshot(conn, path: Path, current: str) -> str:  # noqa: ANN001
    """升之前拍一张。VACUUM INTO 拿到的是一份一致的、能单独打开的库（WAL 里的也在）。

    上次拍完之后库一个字节都没动过的话（升级失败 → 服务反复重启，就是这样），
    那张就是现在的样子，直接用它：否则每重启一次多一整份，最后把盘写满。
    -wal 只在里面真有东西时才算「动过」：标准 SQLite 关连接时删掉它、下次一开又建一个空的，
    光看时间的话每次开机都像是库刚被改过（macOS 自带的那个不删，所以在 Mac 上看不出来）。
    先写 .part、拍完才改名：盘满或者拍到一半被杀，留下的半截不许被下次当成快照复用
    """
    wal = Path(f"{path}-wal")
    changed = max(path.stat().st_mtime, wal.stat().st_mtime if wal.exists() and wal.stat().st_size else 0)
    last = max(path.parent.glob(f"before-migrate-{current}-*.db"), key=lambda p: p.stat().st_mtime, default=None)
    if last is not None and last.stat().st_mtime > changed and last.stat().st_size:
        return str(last)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    shot = path.parent / f"before-migrate-{current}-{stamp}.db"
    part = shot.with_name(shot.name + ".part")
    part.unlink(missing_ok=True)
    try:
        conn.exec_driver_sql("VACUUM INTO ?", (str(part),))
        conn.rollback()
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, shot)
    return str(shot)
