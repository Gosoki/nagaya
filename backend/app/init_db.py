"""建库 / 初始化。

**设计阶段用 create_all**：表结构还在改，每次都生成一份迁移纯属添乱。
等 schema 稳下来、准备录真实账目之前，改走 Alembic（见 alembic/versions/README.md）。
"""

from __future__ import annotations

from sqlmodel import Session, SQLModel, select

from app.db import engine
from app.models import CATEGORY_COLORS, Category, Member
from app.services import settings as settings_svc
from app.services.settings import seed_settings

#: 默认分类，中文。
#: 这些是**用户数据**，不做双语，面板里随时可以改名/增删（SPEC §7.5）。
#: 第四列 monthly＝每月一次的固定项，不在日常记账那屏占按钮，出账单时顺手填。
#: 颜色从 CATEGORY_COLORS 里挑 —— 分类是图标底色，走亮的那一档
#: （成员头像走深的那一档，见 models.py 上那段）
DEFAULT_CATEGORIES = [
    ("房租", "home", CATEGORY_COLORS[0], True),                      # 靛
    ("电费", "bolt", CATEGORY_COLORS[2], True),                      # 琥珀
    ("燃气", "local_fire_department", CATEGORY_COLORS[3], True),     # 红
    ("水费", "water_drop", CATEGORY_COLORS[5], True),                # 天蓝
    ("网费", "wifi", CATEGORY_COLORS[1], True),                      # 青
    ("日用", "shopping_basket", CATEGORY_COLORS[8], False),          # 棕
    ("伙食", "restaurant", CATEGORY_COLORS[6], False),               # 绿
    # 不用 more_horiz（•••）：那个符号在一排分类里读作「还有更多分类」，
    # 而点下去只是选中了一个叫「其他」的分类 —— 实测有人照着它把电费记成了「其他」
    ("其他", "category", CATEGORY_COLORS[9], False),                 # 蓝灰，最中性的那个
]


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_settings(session)
        if not session.exec(select(Category)).first():
            created = [
                Category(name=name, icon=icon, color=color, monthly=monthly, display_order=order)
                for order, (name, icon, color, monthly) in enumerate(DEFAULT_CATEGORIES)
            ]
            session.add_all(created)
            session.commit()
            # 兜底分类指到「其他」（默认表的最后一项）。原来全新部署时它是空的：
            # 没选分类、写了备注的支出按「记入账」毫无反应 —— 前端要把它记进兜底分类，
            # 兜底是 null 就走不下去。只在**这一次新建了分类**时设，
            # 不覆盖用户在面板上主动清空的值
            if settings_svc.get(session, "fallback_category_id") is None:
                session.refresh(created[-1])
                settings_svc.set_(session, "fallback_category_id", created[-1].id)


def has_members() -> bool:
    with Session(engine) as session:
        return session.exec(select(Member)).first() is not None


if __name__ == "__main__":
    init_db()
    print("建库完成：", engine.url)
