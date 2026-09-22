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
from app.services import settings as settings_svc
from app.services.settings import seed_settings


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_settings(s)
        # **备份目录一律指到 tmp。** 不指的话默认是 backend/backups/ ——
        # 用户真备份放在那儿，而任何一条忘了设 backup_path 的用例都会往里写，
        # 假备份和真备份同名同形混在一起，「恢复最新那份」就会盖错东西。
        # 这不是假想：审计的 agent 跑探测时就往里塞了 13 份 5MB 的垃圾
        settings_svc.set_(s, "backup_path", str(tmp_path / "backups"))
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
