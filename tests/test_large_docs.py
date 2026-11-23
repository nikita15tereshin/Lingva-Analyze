"""Тесты Вехи 1: чанкинг больших текстов и пакетная запись в БД."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.crud import create_document, get_document_index_from_db, save_nlp_data_to_db
from src.db.models import Base, LexicalIndex, Sentence, Token
from src.nlp import processor


def test_split_text_chunks_preserves_words():
    text = " ".join(f"Satz_{i} enthält Bundeswehr." for i in range(50))
    chunks = processor._split_text_chunks(text, max_chars=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # ни одно слово не разрезано пополам
    rejoined = " ".join(chunks)
    assert rejoined.count("Bundeswehr.") == 50


def test_process_text_continuous_sent_ids(monkeypatch):
    class FakeNlp:
        def pipe(self, chunks):
            for chunk in chunks:
                sents = []
                for part in [p.strip() for p in chunk.split(".") if p.strip()]:
                    toks = [
                        SimpleNamespace(text=w, lemma_=w.lower(), pos_="NOUN", is_space=False)
                        for w in part.split()
                    ]
                    sents.append(toks)
                yield SimpleNamespace(sents=sents)

    monkeypatch.setattr(processor, "nlp", FakeNlp())
    text = "Erster Satz. Zweiter Satz. Dritter Satz. Vierter Satz."
    res = processor.process_text(text, chunk_size=28)
    ids = [s["sent_id"] for s in res["sentences"]]
    assert ids == list(range(len(ids)))
    assert len(ids) == 4


def test_batch_save_nlp_data_to_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        doc = create_document(db, filename="big_report.pdf", country="DE")
        sentences = [
            {
                "sent_id": i,
                "tokens": [
                    {"word": "Die", "lemma": "der", "pos": "DET"},
                    {"word": "Behörde", "lemma": "Behörde", "pos": "NOUN"},
                    {"word": ".", "lemma": ".", "pos": "PUNCT"},
                ],
            }
            for i in range(120)
        ]
        save_nlp_data_to_db(db, doc.id, {"sentences": sentences})

        assert db.query(Sentence).filter_by(document_id=doc.id).count() == 120
        assert db.query(Token).count() == 2  # der (DET) и Behörde (NOUN), без дублей
        assert db.query(LexicalIndex).count() == 240
        idx = get_document_index_from_db(db, doc.id)
        assert len(idx["Behörde"]) == 120
        assert idx["Behörde"][0] == (0, 1)
        assert idx["Behörde"][-1] == (119, 1)
    finally:
        db.close()
