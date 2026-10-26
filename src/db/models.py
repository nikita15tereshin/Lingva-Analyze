from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class Document(Base):
    """Документ корпуса. Сквозной код вида DE-01 задается при загрузке."""

    __tablename__ = 'documents'

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    external_code = Column(String, unique=True, nullable=True)  # DE-01, AT-02...
    country = Column(String(2), nullable=True)                  # DE / AT / CH
    doc_type = Column(String, nullable=True)                    # спецслужба, полиция, речь...
    title = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    language = Column(String, default="de")
    created_at = Column(DateTime, default=datetime.utcnow)

    sentences = relationship("Sentence", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("country IN ('DE', 'AT', 'CH')", name="ck_documents_country"),
    )


class Sentence(Base):
    __tablename__ = 'sentences'

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete="CASCADE"))
    sentence_number = Column(Integer)
    text = Column(Text, nullable=False)

    document = relationship("Document", back_populates="sentences")
    occurrences = relationship("LexicalIndex", back_populates="sentence", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sentences_document_id", "document_id"),
    )


class Token(Base):
    """Лексема словаря. Различие омонимичных лемм (bestehen V / Bestand N) закрыто полем pos."""

    __tablename__ = 'tokens'

    id = Column(Integer, primary_key=True, index=True)
    lemma = Column(String, nullable=False)
    pos = Column(String, nullable=False, default="_")  # UD-часть речи; "_" — безразлично

    occurrences = relationship("LexicalIndex", back_populates="token")

    __table_args__ = (
        UniqueConstraint("lemma", "pos", name="uq_tokens_lemma_pos"),
    )


class LexicalIndex(Base):
    """Вхождение токена в предложение: позиция и точная словоформа из текста."""

    __tablename__ = 'lexical_index'

    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(Integer, ForeignKey('tokens.id', ondelete="CASCADE"))
    sentence_id = Column(Integer, ForeignKey('sentences.id', ondelete="CASCADE"))
    position = Column(Integer)
    word_form = Column(String, nullable=True)  # musste, gemusst, Polizistin...

    token = relationship("Token", back_populates="occurrences")
    sentence = relationship("Sentence", back_populates="occurrences")

    __table_args__ = (
        Index("ix_lexical_index_sentence_id", "sentence_id"),
        Index("ix_lexical_index_token_id", "token_id"),
    )


class ComparisonResult(Base):
    __tablename__ = 'comparison_results'

    id = Column(Integer, primary_key=True, index=True)
    lemma_a = Column(String, nullable=False)
    lemma_b = Column(String, nullable=False)
    confidence = Column(Float)
    llm_comment = Column(Text)


class RegionalWord(Base):
    """Словарь австрицизмов и гельветизмов (пункты 3.3, P5, P6)."""

    __tablename__ = "regional_dictionary"

    id = Column(Integer, primary_key=True, index=True)
    lemma = Column(String, index=True, nullable=False)
    region = Column(String, index=True, nullable=False)
    standard_de = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("lemma", "region", name="uq_regional_dictionary_lemma_region"),
        CheckConstraint("region IN ('AT', 'CH')", name="ck_regional_dictionary_region"),
    )


class LexicalPair(Base):
    """Пары лексических замен одного понятия в разных вариантах (пункт 3.1, P8)."""

    __tablename__ = "lexical_pairs"

    id = Column(Integer, primary_key=True, index=True)
    concept = Column(String, nullable=False)      # Вооруженные силы
    de_word = Column(String, nullable=True)       # Bundeswehr
    at_word = Column(String, nullable=True)       # Bundesheer
    ch_word = Column(String, nullable=True)       # Schweizer Armee
    note = Column(String, nullable=True)


class QueryParameter(Base):
    """Параметр матрицы сравнительного анализа (P1-P9 и последующие).

    Тип запроса:
    - LEMMA_SET      одно или несколько слов (лемма + опциональная часть речи);
    - LEMMA_AND      все слова должны встретиться в одном предложении (пункт 3.0);
    - WORD_REGEX     регулярка по словоформе (суффикс -in для P9);
    - TEXT_REGEX     регулярка по тексту предложения (параграфы/статьи для P4);
    - LEXICAL_PAIR   подстановка членов пары лексических замен (P8);
    - DICTIONARY     прогон уникальных лемм через regional_dictionary (P5/P6).
    """

    __tablename__ = "query_parameters"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)      # P1, P3, CUSTOM-01...
    name = Column(String, nullable=False)                   # Модальность
    query_type = Column(String, nullable=False)
    markers = Column(Text, nullable=True)                   # JSON-массив маркеров
    max_frequency = Column(Integer, nullable=True)          # фильтр "частота <= N" (прикол А)
    enabled = Column(Integer, nullable=False, default=1)
    comment = Column(String, nullable=True)


class Hit(Base):
    """Найденное вхождение: связь параметра, документа и предложения."""

    __tablename__ = "hits"

    id = Column(Integer, primary_key=True, index=True)
    parameter_id = Column(Integer, ForeignKey('query_parameters.id', ondelete="CASCADE"))
    document_id = Column(Integer, ForeignKey('documents.id', ondelete="CASCADE"))
    sentence_id = Column(Integer, ForeignKey('sentences.id', ondelete="CASCADE"))
    matched_marker = Column(String, nullable=True)  # какая именно лемма/подстрока сработала
    word_form = Column(String, nullable=True)
    run_ts = Column(DateTime, default=datetime.utcnow)

    parameter = relationship("QueryParameter")
    document = relationship("Document")
    sentence = relationship("Sentence")

    __table_args__ = (
        Index("ix_hits_parameter_document", "parameter_id", "document_id"),
        Index("ix_hits_sentence_id", "sentence_id"),
    )


class DictionarySource(Base):
    """Справочник внешних сайтов-словарей (DE/AT/CH), из которых идет выгрузка."""

    __tablename__ = "dictionary_sources"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)     # de_bpb, at_justizonline...
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    region = Column(String, nullable=False)               # DE / AT / CH / ALL
    extraction = Column(String, nullable=False)           # html_table / html_terms / pdf_glossary / termdat_api
    headless = Column(Integer, nullable=False, default=0)
    enabled = Column(Integer, nullable=False, default=1)
    validate = Column(String, nullable=True)              # exclude_de_base и т.п.
    last_sync_at = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    entry_count = Column(Integer, nullable=True)


class DictionaryEntry(Base):
    """Staging: все извлеченные пары слово-значение до ручного отбора.

    status: pending (ждет подтверждения), approved (перенесен в
    regional_dictionary), rejected_format, rejected_germanism.
    """

    __tablename__ = "dictionary_entries"

    id = Column(Integer, primary_key=True, index=True)
    term = Column(String, nullable=False)
    definition = Column(Text, nullable=False)
    region = Column(String, nullable=False)
    source_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("term", "region", "source_key",
                         name="uq_dictionary_entries_term_region_source"),
        Index("ix_dictionary_entries_source_status", "source_key", "status"),
    )
