"""测试用的干净数据库。每个用例一个内存库，互不污染。"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.db  # noqa: F401  —— 导入即注册 PRAGMA（外键约束默认是关的）
from app.models import Member
from app.services.settings import seed_settings


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_settings(s)
        yield s


@pytest.fixture
def members(session: Session) -> list[Member]:
    """三个室友，2026-01-01 一起入住。"""
    rows = [
        Member(name="a", display_name="A", display_order=0, joined_on=dt.date(2026, 1, 1)),
        Member(name="b", display_name="B", display_order=1, joined_on=dt.date(2026, 1, 1)),
        Member(name="c", display_name="C", display_order=2, joined_on=dt.date(2026, 1, 1)),
    ]
    for m in rows:
        session.add(m)
    session.commit()
    for m in rows:
        session.refresh(m)
    return rows
