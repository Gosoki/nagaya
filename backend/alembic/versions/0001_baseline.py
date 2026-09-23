"""基线：2026-09-23 的整套表结构（D18 那天切 Alembic；当晚把 0001、0002 合成了这一份）。

从空库建起。切 Alembic 之前 create_all 建的旧格式库（没有 alembic_version）
**不再接管**：app/migrate.py 开机时认出来就拒绝启动，并说清为什么。

Revision ID: 0001
Revises:
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel          # SQLModel 的 AutoString 等类型，autogenerate 会用到


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('app_icon',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('png', sa.LargeBinary(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('bundle',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('member',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('color', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('joined_on', sa.Date(), nullable=False),
    sa.Column('left_on', sa.Date(), nullable=True),
    sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('lang', sa.Enum('zh', 'ja', name='lang'), nullable=False),
    sa.Column('avatar', sa.LargeBinary(), nullable=True),
    sa.Column('avatar_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_member_display_order', 'member', ['display_order'], unique=False)
    op.create_index('ix_member_name', 'member', ['name'], unique=True)

    op.create_table('setting',
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('value_json', sa.JSON(), nullable=True),
    sa.Column('note_zh', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('note_ja', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )

    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('member_id', sa.Integer(), nullable=True),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('target_table', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('before_json', sa.JSON(), nullable=True),
    sa.Column('after_json', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['member_id'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_action', 'audit_log', ['action'], unique=False)
    op.create_index('ix_audit_log_at', 'audit_log', ['at'], unique=False)
    op.create_index('ix_audit_log_member_id', 'audit_log', ['member_id'], unique=False)
    op.create_index('ix_audit_log_target_id', 'audit_log', ['target_id'], unique=False)
    op.create_index('ix_audit_log_target_table', 'audit_log', ['target_table'], unique=False)

    op.create_table('category',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('color', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('default_rule_json', sa.JSON(), nullable=True),
    sa.Column('monthly', sa.Boolean(), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('default_payer_id', sa.Integer(), nullable=True),
    sa.Column('same_as_last', sa.Boolean(), nullable=False),
    sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['default_payer_id'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_category_archived', 'category', ['archived'], unique=False)
    op.create_index('ix_category_display_order', 'category', ['display_order'], unique=False)
    op.create_index('ix_category_monthly', 'category', ['monthly'], unique=False)
    op.create_index('ix_category_name', 'category', ['name'], unique=False)

    op.create_table('member_pref',
    sa.Column('member_id', sa.Integer(), nullable=False),
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('value', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['member_id'], ['member.id'], ),
    sa.PrimaryKeyConstraint('member_id', 'key')
    )

    op.create_table('memo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('body', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_memo_display_order', 'memo', ['display_order'], unique=False)

    op.create_table('statement',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('label', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('cut_at', sa.DateTime(), nullable=False),
    sa.Column('covers_from', sa.Date(), nullable=True),
    sa.Column('covers_to', sa.Date(), nullable=True),
    sa.Column('cut_by', sa.Integer(), nullable=True),
    sa.Column('snapshot_json', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['cut_by'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_statement_cut_at', 'statement', ['cut_at'], unique=False)
    op.create_index('ix_statement_label', 'statement', ['label'], unique=False)

    op.create_table('entry',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('expense', 'income', 'settlement', name='entrykind'), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('amount_jpy', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('payer_id', sa.Integer(), nullable=False),
    sa.Column('to_member_id', sa.Integer(), nullable=True),
    sa.Column('statement_id', sa.Integer(), nullable=True),
    sa.Column('bundle_id', sa.Integer(), nullable=True),
    sa.Column('split_rule_json', sa.JSON(), nullable=True),
    sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('receipt_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['bundle_id'], ['bundle.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['category.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['member.id'], ),
    sa.ForeignKeyConstraint(['payer_id'], ['member.id'], ),
    sa.ForeignKeyConstraint(['statement_id'], ['statement.id'], ),
    sa.ForeignKeyConstraint(['to_member_id'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_entry_bundle_id', 'entry', ['bundle_id'], unique=False)
    op.create_index('ix_entry_category_id', 'entry', ['category_id'], unique=False)
    op.create_index('ix_entry_date', 'entry', ['date'], unique=False)
    op.create_index('ix_entry_kind', 'entry', ['kind'], unique=False)
    op.create_index('ix_entry_payer_id', 'entry', ['payer_id'], unique=False)
    op.create_index('ix_entry_statement_id', 'entry', ['statement_id'], unique=False)

    op.create_table('template',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('kind', sa.Enum('expense', 'income', 'settlement', name='entrykind'), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('payer_default_id', sa.Integer(), nullable=True),
    sa.Column('amount_default', sa.Integer(), nullable=True),
    sa.Column('rule_json', sa.JSON(), nullable=True),
    sa.Column('items_json', sa.JSON(), nullable=True),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['category.id'], ),
    sa.ForeignKeyConstraint(['payer_default_id'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('entry_share',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('entry_id', sa.Integer(), nullable=False),
    sa.Column('member_id', sa.Integer(), nullable=False),
    sa.Column('amount_jpy', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['entry_id'], ['entry.id'], ),
    sa.ForeignKeyConstraint(['member_id'], ['member.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entry_id', 'member_id', name='uq_share_entry_member')
    )
    op.create_index('ix_entry_share_member_id', 'entry_share', ['member_id'], unique=False)

    op.create_table('request_key',
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('entry_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['entry_id'], ['entry.id'], ),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    # 基线之下没有版本。要一个空库就换个 NAGAYA_DB 路径，别在账本上 drop 表
    raise NotImplementedError("基线之下没有版本")
