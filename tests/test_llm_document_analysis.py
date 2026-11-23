# Тесты Вехи 4: качественный LLM-анализ документа и эндпоинт API.

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analysis import llm
from src.api import main as api_main
from src.db.crud import create_document, save_nlp_data_to_db
from src.db.models import Base


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


def _seed_doc(db):
    doc = create_document(db, filename="DE-01.pdf", country="DE", external_code="DE-01")
    save_nlp_data_to_db(db, doc.id, {
        "sentences": [
            {
                "sent_id": 0,
                "tokens": [
                    {"word": "Spionage", "lemma": "Spionage", "pos": "NOUN"},
                    {"word": "und", "lemma": "und", "pos": "CCONJ"},
                    {"word": "Extremismus", "lemma": "Extremismus", "pos": "NOUN"},
                ],
            },
            {
                "sent_id": 1,
                "tokens": [
                    {"word": "Russland", "lemma": "Russland", "pos": "PROPN"},
                    {"word": "und", "lemma": "und", "pos": "CCONJ"},
                    {"word": "China", "lemma": "China", "pos": "PROPN"},
                ],
            },
        ]
    })
    return doc


def test_sample_document_text_truncates_large_corpus():
    sents = [f"Satz nummer {i} mit Text." for i in range(200)]
    excerpt = llm._sample_document_text(sents, max_chars=300)
    assert "[СЕРЕДИНА ДОКУМЕНТА]" in excerpt
    assert "[КОНЦОВКА ДОКУМЕНТА]" in excerpt


def test_parse_json_response_strips_markdown_fence():
    payload = {"tone": {"main_focus": "innere Sicherheit"}, "main_threats": ["Spionage"]}
    raw = "```json" + chr(10) + json.dumps(payload) + chr(10) + "```"
    assert llm._parse_json_response(raw) == payload
    assert llm._parse_json_response("не json") == {"raw_response": "не json"}


def test_analyze_document_qualitative_and_api(db_session, monkeypatch):
    db, Session = db_session
    doc = _seed_doc(db)
    monkeypatch.setattr(api_main, "SessionLocal", Session)

    fake_json = json.dumps({
        "structure": {"chapters": 3, "estimated_scope": "short"},
        "tone": {"main_focus": "Verfassungsschutz"},
        "main_threats": ["Spionage", "Extremismus"],
        "geopolitical_attitude": {"russia": "критическое", "china": "настороженное"},
        "stylistic_notes": {"metaphors": [], "historical_references": []},
    }, ensure_ascii=False)
    monkeypatch.setattr(llm, "complete_once", lambda prompt: fake_json)

    client = TestClient(api_main.app)
    resp = client.post(f"/api/documents/{doc.id}/llm-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == doc.id
    assert "Spionage" in body["analysis"]["main_threats"]

    resp_404 = client.post("/api/documents/999/llm-analysis")
    assert resp_404.status_code == 404
