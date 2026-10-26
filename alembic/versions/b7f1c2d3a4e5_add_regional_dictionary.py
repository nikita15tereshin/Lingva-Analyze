"""Add regional_dictionary table and lookup indexes

Revision ID: b7f1c2d3a4e5
Revises: 33d4c45279cd
Create Date: 2026-10-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f1c2d3a4e5'
down_revision: Union[str, Sequence[str], None] = '33d4c45279cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Таблица словаря австрицизмов и гельветизмов (модель src.db.models.RegionalWord).
    op.create_table(
        'regional_dictionary',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lemma', sa.String(), nullable=False),
        sa.Column('region', sa.String(), nullable=False),
        sa.Column('standard_de', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_regional_dictionary_id'), 'regional_dictionary', ['id'], unique=False)
    op.create_index(op.f('ix_regional_dictionary_lemma'), 'regional_dictionary', ['lemma'], unique=False)
    op.create_index(op.f('ix_regional_dictionary_region'), 'regional_dictionary', ['region'], unique=False)

    # Индексы для частых запросов: выборка предложений документа и вхождений леммы.
    op.create_index('ix_sentences_document_id', 'sentences', ['document_id'], unique=False)
    op.create_index('ix_lexical_index_sentence_id', 'lexical_index', ['sentence_id'], unique=False)
    op.create_index('ix_lexical_index_token_id', 'lexical_index', ['token_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_lexical_index_token_id', table_name='lexical_index')
    op.drop_index('ix_lexical_index_sentence_id', table_name='lexical_index')
    op.drop_index('ix_sentences_document_id', table_name='sentences')
    op.drop_index(op.f('ix_regional_dictionary_region'), table_name='regional_dictionary')
    op.drop_index(op.f('ix_regional_dictionary_lemma'), table_name='regional_dictionary')
    op.drop_index(op.f('ix_regional_dictionary_id'), table_name='regional_dictionary')
    op.drop_table('regional_dictionary')
