设计阶段这里是空的 —— schema 还在改，生成的迁移明天就过期。

**等表结构稳下来、准备录真实账目之前**，跑一次：

    .venv/bin/alembic revision --autogenerate -m "建初始表结构"
    .venv/bin/alembic upgrade head

env.py 和 script.py.mako 都已经配好了（含 SQLModel 的 `import sqlmodel` 坑和
SQLite 必需的 render_as_batch），到时候直接生成即可。

在那之前，建库走 `app/init_db.py` 的 create_all。
