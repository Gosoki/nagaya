"""开机把库升到最新的表结构（Alembic）。

D18 定的是「录真账之前切 Alembic」，这就是那一步。之前一直是 create_all ——
它只会建缺的表，**不会给已有的表加列**，于是每加一个字段，老库一开就是
`no such column`，加字段之前做的备份也就恢复不回来了。

现在：改了模型就写一份迁移（alembic/versions/README.md 里有怎么写），
开机自动升；恢复一份旧备份时也先按同样的步骤升一遍（tools/restore.py）。

三件事缺一不可：
  * **升之前先拍一张快照**（只在真有要升的版本时）：SQLite 的整表重建
    （改列要靠它）中途失败的话，库会停在半截，得有一份能退回去的；
  * **升的时候关掉外键**：整表重建要先删旧表再改名，外键开着的话，
    删一张被引用的表会连带清掉引用它的行，或者直接失败（Alembic 文档的原话）；
  * **升完核对**：库里的列和模型对不上就拒绝启动。比「起来了，查到那一列才 500」好。
"""

from __future__ import annotations

import datetime as dt
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
                + " —— 这份库比迁移的基线还旧，自动升不上来。"
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


def _snapshot(conn, path: Path, current: str | None) -> str:  # noqa: ANN001
    """升之前拍一张。VACUUM INTO 拿到的是一份一致的、能单独打开的库（WAL 里的也在）"""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    shot = path.parent / f"before-migrate-{current or 'legacy'}-{stamp}.db"
    conn.exec_driver_sql("VACUUM INTO ?", (str(shot),))
    conn.rollback()
    return str(shot)
