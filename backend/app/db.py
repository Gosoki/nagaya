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

# 新建的文件只给自己读写。run.sh 里那句 umask 管不到先于它建库的入口 ——
# 照 README 先跑 tools.add_member 的话，账本（含密码哈希）就是 0644，
# 而 SQLite 之后建的 -wal/-shm 照抄主库的权限，从此一直是别人可读。每个入口都 import 这里
os.umask(0o077)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    # 常驻 1 条，忙的时候最多再开 4 条。默认是常驻 5 条、最多 15 条 —— 每条都揣着
    # 自己的页缓存和表结构，开了就不还。三个人的账本同一时刻真在查库的也就一两个请求；
    # 而且 SQLite 同一时刻只许一个人写，多开的连接只是在排队抢锁（实测连接少了反而快）
    pool_size=1,
    max_overflow=4,
)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")   # 默认是 OFF，不打开等于没有外键
    cur.execute("PRAGMA synchronous=NORMAL")
    # 两个人同时写时先等一会儿再说。不设的话 SQLite 立刻抛 "database is locked"，
    # 而那对用户来说就是记账随机失败一次，重试又好了 —— 最难查的那种
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
