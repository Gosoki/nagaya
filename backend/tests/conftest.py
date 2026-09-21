"""测试用的干净数据库。每个用例一个内存库，互不污染。"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from fastapi.testclient import TestClient

import app.db  # noqa: F401  —— 导入即注册 PRAGMA（外键约束默认是关的）
from app.auth import hash_password
from app.db import get_session
from app.main import app as fastapi_app
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


@pytest.fixture
def client(session: Session):
    fastapi_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(fastapi_app)   # 不用 with：避免触发 lifespan 去建真实的库
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def auth(client: TestClient, session: Session, members: list[Member]) -> dict[str, str]:
    """以 A 的身份登录，返回请求头。"""
    a = members[0]
    a.password_hash = hash_password("pw123456")
    session.add(a)
    session.commit()
    r = client.post("/api/auth/login", json={"name": "a", "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
