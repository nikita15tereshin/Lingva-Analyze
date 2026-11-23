# Тесты Вехи 3: сравнение двух документов и эндпоинт POST /api/compare.

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import main as api_main
from src.db.crud import create_document, save_nlp_data_to_db
from src.db.models import Base, DictionaryEntry, RegionalWord
from src.query.compare import compare_documents


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session, Session
    session.close()


def _seed_two_docs(db):
    doc_a = create_document(db, filename="AT-01.pdf", country="AT", external_code="AT-01")
    doc_b = create_document(db, filename="CH-01.pdf", country="CH", external_code="CH-01")

    save_nlp_data_to_db(db, doc_a.id, {
        "sentences": [{
            "sent_id": 0,
            "tokens": [
                {"word": "Die", "lemma": "der", "pos": "DET"},
                {"word": "Marille", "lemma": "Marille", "pos": "NOUN"},
                {"word": "ist", "lemma": "sein", "pos": "AUX"},
                {"word": "gut", "lemma": "gut", "pos": "ADJ"},
            ],
        }]
    })
    save_nlp_data_to_db(db, doc_b.id, {
        "sentences": [{
            "sent_id": 0,
            "tokens": [
                {"word": "Das", "lemma": "der", "pos": "DET"},
                {"word": "Billett", "lemma": "Billett", "pos": "NOUN"},
                {"word": "und", "lemma": "und", "pos": "CCONJ"},
                {"word": "Velo", "lemma": "Velo", "pos": "NOUN"},
            ],
        }]
    })

    # Marille в regional_dictionary, Billett в dictionary_entries (approved), Velo — pending (должен игнорироваться)
    db.add(RegionalWord(lemma="Marille", region="AT", standard_de="Aprikose"))
    db.add(DictionaryEntry(term="Billett", definition="Fahrkarte", region="CH", source_key="ch_test", status="approved"))
    db.add(DictionaryEntry(term="Velo", definition="Fahrrad", region="CH", source_key="ch_test", status="pending"))
    db.commit()
    return doc_a, doc_b


def test_compare_documents_filters_approved_and_returns_contexts(db_session):
    db, _ = db_session
    doc_a, doc_b = _seed_two_docs(db)

    res = compare_documents(db, doc_a.id, doc_b.id)
    assert res["doc_a"]["id"] == doc_a.id
    assert res["doc_b"]["id"] == doc_b.id
    assert len(res["unique_a_regional"]) == 1
    assert res["unique_a_regional"][0]["lemma"] == "Marille"
    assert res["unique_a_regional"][0]["meaning"] == "Aprikose"
    assert "Marille" in res["unique_a_regional"][0]["contexts"][0]

    assert len(res["unique_b_regional"]) == 1
    assert res["unique_b_regional"][0]["lemma"] == "Billett"
    assert res["unique_b_regional"][0]["meaning"] == "Fahrkarte"


def test_api_compare_endpoint(db_session, monkeypatch):
    db, Session = db_session
    doc_a, doc_b = _seed_two_docs(db)
    monkeypatch.setattr(api_main, "SessionLocal", Session)

    client = TestClient(api_main.app)
    resp = client.post("/api/compare", json={"doc_a_id": doc_a.id, "doc_b_id": doc_b.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unique_a_regional"][0]["lemma"] == "Marille"
    assert body["unique_b_regional"][0]["lemma"] == "Billett"

    resp_404 = client.post("/api/compare", json={"doc_a_id": 999, "doc_b_id": doc_b.id})
    assert resp_404.status_code == 404
