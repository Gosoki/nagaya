"""数据库连接 —— SQLite + WAL。

WAL 让「一个人在手机上记账」和「另一个人在电脑上看账单」不互相阻塞。
外键约束 SQLite 默认是**关着**的，必须每条连接显式打开，否则 entry_share
指向一个不存在的 entry 都不会报错。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

DB_PATH = Path(os.getenv("NAGAYA_DB", Path(__file__).parents[1] / "data" / "nagaya.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")   # 默认是 OFF，不打开等于没有外键
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
