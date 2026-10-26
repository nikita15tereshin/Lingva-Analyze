"""Сквозная проверка движка матрицы: индексация -> прогон параметров -> статистика."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Token, LexicalIndex
from src.db.crud import create_document, save_nlp_data_to_db, get_frequency_table
from src.query.defaults import seed_defaults
from src.query import engine as qe


DE_SENTENCES = [
    "Die Polizistin muss den Bericht prüfen.",
    "Das § 1 des Gesetzes wird wohl man akzeptieren.",
    "Wir haben Jänner 2024 in Wien diskutiert.",
]

AT_SENTENCES = [
    "Der Bundesheer Offizier sagte das Wort Jänner oft.",
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def indexed_corpus(db):
    """Индексируем два «документа» вручную (без spaCy), с pos и word_form."""
    doc_de = create_document(db, "de_report.txt", country="DE", external_code="DE-01")
    doc_at = create_document(db, "at_report.txt", country="AT", external_code="AT-01")

    def fake_nlp(sentences):
        return {"sentences": [
            {"sent_id": i, "tokens": [
                {"word": w, "lemma": lem, "pos": pos}
                for w, lem, pos in s
            ]}
            for i, s in enumerate(sentences)
        ]}

    save_nlp_data_to_db(db, doc_de.id, fake_nlp([
        [("Polizistin", "Polizist", "NOUN"), ("muss", "müssen", "VERB"), ("Bericht", "Bericht", "NOUN"), (".", ".", "PUNCT")],
        [("§", "§", "SYM"), ("1", "1", "NUM"), ("des", "der", "DET"), ("Gesetzes", "Gesetz", "NOUN"), ("wird", "werden", "AUX"), ("wohl", "wohl", "ADV"), ("man", "man", "PRON")],
        [("Jänner", "Jänner", "NOUN"), ("2024", "2024", "NUM")],
    ]))
    save_nlp_data_to_db(db, doc_at.id, fake_nlp([
        [("Bundesheer", "Bundesheer", "NOUN"), ("Jänner", "Jänner", "NOUN")],
    ]))
    return doc_de, doc_at


def test_positions_skip_punctuation(db, indexed_corpus):
    doc_de, _ = indexed_corpus
    occ = (
        db.query(LexicalIndex)
        .join(Token, LexicalIndex.token_id == Token.id)
        .filter(Token.lemma == "Bericht").first()
    )
    assert occ.position == 2          # Punkt не сдвигает нумерацию слов
    assert occ.word_form == "Bericht"


def test_frequency_table(db, indexed_corpus):
    doc_de, _ = indexed_corpus
    table = get_frequency_table(db, doc_de.id)
    assert {"lemma": "Jänner", "pos": "NOUN", "count": 1} in table


def test_seed_and_lemma_set(db, indexed_corpus):
    seed_defaults(db)
    param = db.query(type(db).__module__ and __import__("src.db.models", fromlist=["QueryParameter"]).QueryParameter).first() \
        if False else None
    from src.db.models import QueryParameter
    p1 = db.query(QueryParameter).filter(QueryParameter.code == "P1").first()
    assert p1 is not None
    res = qe.run_parameter(db, p1)
    assert res["hits"] == 1  # только müssen в DE-документе


def test_lemma_and_combination(db, indexed_corpus):
    from src.db.models import QueryParameter
    seed_defaults(db)
    p = QueryParameter(code="TEST-AND", name="wohl + man", query_type="LEMMA_AND",
                       markers='[{"lemma": "wohl"}, {"lemma": "man"}]')
    db.add(p); db.commit()
    res = qe.run_parameter(db, p)
    assert res["hits"] == 1
    contexts = qe.hits_with_context(db, "TEST-AND")
    assert "wohl" in contexts[0]["sentence"]


def test_word_regex_gender(db, indexed_corpus):
    from src.db.models import QueryParameter
    p = QueryParameter(code="TEST-IN", name="суффикс -in", query_type="WORD_REGEX",
                       markers='["in$"]')
    db.add(p); db.commit()
    res = qe.run_parameter(db, p)
    assert res["hits"] == 1
    row = qe.hits_with_context(db, "TEST-IN")[0]
    assert row["word_form"] == "Polizistin"


def test_text_regex_paragraph_and_year(db, indexed_corpus):
    from src.db.models import QueryParameter
    p = QueryParameter(code="TEST-P4", name="параграфы", query_type="TEXT_REGEX",
                       markers=json.dumps([r"§\s*\d+"]))
    db.add(p); db.commit()
    assert qe.run_parameter(db, p)["hits"] == 1

    y = QueryParameter(code="TEST-YR", name="годы", query_type="TEXT_REGEX",
                       markers=json.dumps([r"\b(1[89]\d{2}|20\d{2})\b"]))
    db.add(y); db.commit()
    assert qe.run_parameter(db, y)["hits"] == 1


def test_lexical_pair_and_country_stats(db, indexed_corpus):
    from src.db.models import QueryParameter
    seed_defaults(db)
    p8 = db.query(QueryParameter).filter(QueryParameter.code == "P8").first()
    res = qe.run_parameter(db, p8)
    assert res["hits"] >= 1  # Bundesheer в AT-документе

    stats = qe.statistics_by_country(db, "P8")
    assert any(s["country"] == "AT" for s in stats)


def test_dictionary_run(db, indexed_corpus):
    from src.db.models import QueryParameter, RegionalWord
    seed_defaults(db)
    db.add(RegionalWord(lemma="Jänner", region="AT", standard_de="Januar"))
    db.commit()
    p5 = db.query(QueryParameter).filter(QueryParameter.code == "P5-P6").first()
    res = qe.run_parameter(db, p5)
    assert res["hits"] == 2  # Jänner есть в обоих документах


def test_rerun_replaces_hits(db, indexed_corpus):
    from src.db.models import QueryParameter
    seed_defaults(db)
    p1 = db.query(QueryParameter).filter(QueryParameter.code == "P1").first()
    qe.run_parameter(db, p1)
    qe.run_parameter(db, p1)
    assert len(qe.hits_with_context(db, "P1")) == 1  # без дублей
