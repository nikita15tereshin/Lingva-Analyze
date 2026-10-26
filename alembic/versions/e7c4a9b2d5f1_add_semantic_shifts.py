"""Add semantic_shifts table and hits.resolution column (P7 hybrid classifier)

Revision ID: e7c4a9b2d5f1
Revises: d8b3e6f1a2c4
Create Date: 2026-10-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c4a9b2d5f1'
down_revision: Union[str, Sequence[str], None] = 'd8b3e6f1a2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'semantic_shifts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('concept', sa.String(), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('meaning', sa.String(), nullable=False),
        sa.Column('collocations', sa.Text(), nullable=True),
        sa.Column('examples', sa.Text(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.CheckConstraint("country IN ('DE', 'AT', 'CH')",
                           name='ck_semantic_shifts_country'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('word', 'country', 'meaning',
                            name='uq_semantic_shifts_word_country_meaning'),
    )
    op.create_index(op.f('ix_semantic_shifts_id'), 'semantic_shifts', ['id'], unique=False)
    op.create_index(op.f('ix_semantic_shifts_word'), 'semantic_shifts', ['word'], unique=False)

    op.add_column('hits', sa.Column('resolution', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('hits', 'resolution')
    op.drop_index(op.f('ix_semantic_shifts_word'), table_name='semantic_shifts')
    op.drop_index(op.f('ix_semantic_shifts_id'), table_name='semantic_shifts')
    op.drop_table('semantic_shifts')
