"""member.away：离家模式

开着时新记「离家时不算的那一类」（设置 away_category_id，默认伙食）默认不算这个人一份。
人还在籍，和 left_on 是两回事。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOT NULL 新列要给 server_default：老库里已有的成员行没有这一格，不给就加不进去
    with op.batch_alter_table("member", schema=None) as batch_op:
        batch_op.add_column(sa.Column("away", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("member", schema=None) as batch_op:
        batch_op.drop_column("away")
