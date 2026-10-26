"""Add matrix engine: document attributes, token pos, word_form, lookup tables

Revision ID: c9a2f5d8e1b0
Revises: b7f1c2d3a4e5
Create Date: 2026-10-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9a2f5d8e1b0'
down_revision: Union[str, Sequence[str], None] = 'b7f1c2d3a4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Атрибуты корпуса: DE-01 / AT-02, страна, тип документа (пункт 4.4 ТЗ)
    with op.batch_alter_table('documents') as batch_op:
        batch_op.add_column(sa.Column('external_code', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('doc_type', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('title', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('year', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_documents_external_code', ['external_code'])

    # Лемма больше не уникальна глобально: различаем омонимы по части речи
    with op.batch_alter_table('tokens') as batch_op:
        batch_op.drop_index('ix_tokens_lemma')
        batch_op.add_column(sa.Column('pos', sa.String(), nullable=False, server_default='_'))
        batch_op.create_unique_constraint('uq_tokens_lemma_pos', ['lemma', 'pos'])

    # Точная словоформа вхождения (для подсветки и regex по форме)
    with op.batch_alter_table('lexical_index') as batch_op:
        batch_op.add_column(sa.Column('word_form', sa.String(), nullable=True))

    # Справочник лексических замен (P8)
    op.create_table(
        'lexical_pairs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('concept', sa.String(), nullable=False),
        sa.Column('de_word', sa.String(), nullable=True),
        sa.Column('at_word', sa.String(), nullable=True),
        sa.Column('ch_word', sa.String(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_lexical_pairs_id'), 'lexical_pairs', ['id'], unique=False)

    # Параметры матрицы анализа
    op.create_table(
        'query_parameters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('query_type', sa.String(), nullable=False),
        sa.Column('markers', sa.Text(), nullable=True),
        sa.Column('max_frequency', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('comment', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index(op.f('ix_query_parameters_id'), 'query_parameters', ['id'], unique=False)

    # Результаты прогонов
    op.create_table(
        'hits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('parameter_id', sa.Integer(), nullable=True),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('sentence_id', sa.Integer(), nullable=True),
        sa.Column('matched_marker', sa.String(), nullable=True),
        sa.Column('word_form', sa.String(), nullable=True),
        sa.Column('run_ts', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parameter_id'], ['query_parameters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sentence_id'], ['sentences.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_hits_id'), 'hits', ['id'], unique=False)
    op.create_index('ix_hits_parameter_document', 'hits', ['parameter_id', 'document_id'], unique=False)
    op.create_index('ix_hits_sentence_id', 'hits', ['sentence_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_hits_sentence_id', table_name='hits')
    op.drop_index('ix_hits_parameter_document', table_name='hits')
    op.drop_index(op.f('ix_hits_id'), table_name='hits')
    op.drop_table('hits')
    op.drop_index(op.f('ix_query_parameters_id'), table_name='query_parameters')
    op.drop_table('query_parameters')
    op.drop_index(op.f('ix_lexical_pairs_id'), table_name='lexical_pairs')
    op.drop_table('lexical_pairs')

    with op.batch_alter_table('lexical_index') as batch_op:
        batch_op.drop_column('word_form')

    with op.batch_alter_table('tokens') as batch_op:
        batch_op.drop_constraint('uq_tokens_lemma_pos', type_='unique')
        batch_op.drop_column('pos')
        batch_op.create_index('ix_tokens_lemma', ['lemma'], unique=True)

    with op.batch_alter_table('documents') as batch_op:
        batch_op.drop_constraint('uq_documents_external_code', type_='unique')
        batch_op.drop_column('year')
        batch_op.drop_column('title')
        batch_op.drop_column('doc_type')
        batch_op.drop_column('country')
        batch_op.drop_column('external_code')
