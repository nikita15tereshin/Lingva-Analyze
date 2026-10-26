import pytest

from src.db.models import Base, Document, RegionalWord
from src.db.crud import (
    create_document,
    save_nlp_data_to_db,
    get_document_index_from_db,
)
from src.analysis.context import get_contexts_for_lemma
from src.analysis.matcher import classify_unique_words


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.db.session import engine

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


NLP_DATA = {
    "sentences": [
        {
            "sent_id": 0,
            "tokens": [
                {"word": "Die", "lemma": "die", "pos": "DET"},
                {"word": "Marille", "lemma": "Marille", "pos": "NOUN"},
                {"word": ".", "lemma": ".", "pos": "PUNCT"},
            ],
        },
        {
            "sent_id": 1,
            "tokens": [
                {"word": "Die", "lemma": "die", "pos": "DET"},
                {"word": "Marille", "lemma": "Marille", "pos": "NOUN"},
                {"word": "schmeckt", "lemma": "schmecken", "pos": "VERB"},
                {"word": ".", "lemma": ".", "pos": "PUNCT"},
            ],
        },
    ]
}


def test_create_and_save_document(db):
    doc = create_document(db, filename="AT-01.pdf")
    assert doc.id is not None

    save_nlp_data_to_db(db, doc.id, NLP_DATA)

    index = get_document_index_from_db(db, doc.id)
    assert set(index.keys()) == {"die", "Marille", "schmecken"}
    assert sorted(index["Marille"]) == [(0, 1), (1, 1)]


def test_get_contexts_for_lemma(db):
    doc = create_document(db, filename="AT-02.pdf")
    save_nlp_data_to_db(db, doc.id, NLP_DATA)

    contexts = get_contexts_for_lemma(db, "Marille", doc.id)
    assert len(contexts) == 2
    assert "Marille" in contexts[0]["target_sentence"]
    # Окно контекста включает соседнее предложение
    assert "schmeckt" in contexts[0]["full_context"]


def test_classify_unique_words(db):
    doc = create_document(db, filename="AT-03.pdf")
    save_nlp_data_to_db(db, doc.id, NLP_DATA)

    db.add(RegionalWord(lemma="Marille", region="AT", standard_de="Aprikose"))
    db.add(RegionalWord(lemma="Billett", region="CH", standard_de="Fahrkarte"))
    db.commit()

    result = classify_unique_words(db, ["Marille", "Billett", "Schweizerische"])
    assert result["AT_matches"][0]["standard_de"] == "Aprikose"
    assert result["CH_matches"][0]["lemma"] == "Billett"
    assert result["unknown"] == ["Schweizerische"]
