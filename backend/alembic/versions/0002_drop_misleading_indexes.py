"""去掉两个帮倒忙的索引

* `ix_entry_deleted_at`：几乎每一行都是 NULL，SQLite 却把 `deleted_at IS NULL`
  当等值条件、拿它开路 —— 「最近 500 笔」于是先扫整本账再排序（5 年规模 9.6ms，
  去掉之后走日期索引 0.7ms）。ANALYZE 救不回来。
* `ix_entry_share_entry_id`：和 (entry_id, member_id) 唯一约束自带的索引重复，
  只增加写入成本。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_entry_deleted_at', table_name='entry', if_exists=True)
    op.drop_index('ix_entry_share_entry_id', table_name='entry_share', if_exists=True)


def downgrade() -> None:
    op.create_index('ix_entry_deleted_at', 'entry', ['deleted_at'], unique=False)
    op.create_index('ix_entry_share_entry_id', 'entry_share', ['entry_id'], unique=False)
