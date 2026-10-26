"""Add dictionary_sources and dictionary_entries (parser staging tables)

Revision ID: d8b3e6f1a2c4
Revises: c9a2f5d8e1b0
Create Date: 2026-10-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8b3e6f1a2c4'
down_revision: Union[str, Sequence[str], None] = 'c9a2f5d8e1b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dictionary_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('region', sa.String(), nullable=False),
        sa.Column('extraction', sa.String(), nullable=False),
        sa.Column('headless', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('enabled', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('validate', sa.String(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('entry_count', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_dictionary_sources_id'), 'dictionary_sources', ['id'], unique=False)
    op.create_index(op.f('ix_dictionary_sources_key'), 'dictionary_sources', ['key'], unique=True)

    op.create_table(
        'dictionary_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('term', sa.String(), nullable=False),
        sa.Column('definition', sa.Text(), nullable=False),
        sa.Column('region', sa.String(), nullable=False),
        sa.Column('source_key', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('term', 'region', 'source_key',
                            name='uq_dictionary_entries_term_region_source'),
    )
    op.create_index(op.f('ix_dictionary_entries_id'), 'dictionary_entries', ['id'], unique=False)
    op.create_index(op.f('ix_dictionary_entries_term'), 'dictionary_entries', ['term'], unique=False)
    op.create_index('ix_dictionary_entries_source_status', 'dictionary_entries',
                    ['source_key', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_dictionary_entries_source_status', table_name='dictionary_entries')
    op.drop_index(op.f('ix_dictionary_entries_term'), table_name='dictionary_entries')
    op.drop_index(op.f('ix_dictionary_entries_id'), table_name='dictionary_entries')
    op.drop_table('dictionary_entries')
    op.drop_index(op.f('ix_dictionary_sources_key'), table_name='dictionary_sources')
    op.drop_index(op.f('ix_dictionary_sources_id'), table_name='dictionary_sources')
    op.drop_table('dictionary_sources')
