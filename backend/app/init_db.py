"""建库 / 初始化。

**设计阶段用 create_all**：表结构还在改，每次都生成一份迁移纯属添乱。
等 schema 稳下来、准备录真实账目之前，改走 Alembic（见 alembic/versions/README.md）。
"""

from __future__ import annotations

from sqlmodel import Session, SQLModel, select

from app.db import engine
from app.models import PALETTE, Category, Member
from app.services.settings import seed_settings

#: 默认分类，中文。
#: 这些是**用户数据**，不做双语，面板里随时可以改名/增删（SPEC §7.5）。
#: 第四列 monthly＝每月一次的固定项，不在日常记账那屏占按钮，出账单时顺手填。
#: 颜色一律从 PALETTE 里挑 —— 分类图标和成员头像在账单页上下挨着，
#: 两套色阶（亮的分类 + 深的头像）放一起像两个 App 拼起来的
DEFAULT_CATEGORIES = [
    ("房租", "home", PALETTE[0], True),                        # 靛
    ("电费", "bolt", PALETTE[2], True),                        # 橙
    ("燃气", "local_fire_department", PALETTE[3], True),       # 红
    ("水费", "water_drop", PALETTE[5], True),                  # 蓝绿
    ("网费", "wifi", PALETTE[1], True),                        # 青
    ("日用品", "shopping_basket", PALETTE[4], False),          # 紫
    ("伙食", "restaurant", PALETTE[6], False),                 # 绿
    # 不用 more_horiz（•••）：那个符号在一排分类里读作「还有更多分类」，
    # 而点下去只是选中了一个叫「其他」的分类 —— 实测有人照着它把电费记成了「其他」
    ("其他", "category", PALETTE[9], False),                   # 蓝灰，最中性的那个
]


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_settings(session)
        if not session.exec(select(Category)).first():
            for order, (name, icon, color, monthly) in enumerate(DEFAULT_CATEGORIES):
                session.add(
                    Category(
                        name=name, icon=icon, color=color,
                        monthly=monthly, display_order=order,
                    )
                )
            session.commit()


def has_members() -> bool:
    with Session(engine) as session:
        return session.exec(select(Member)).first() is not None


if __name__ == "__main__":
    init_db()
    print("建库完成：", engine.url)
