"""Гибридный классификатор P7: правила разметляют большинство, LLM - только спорные."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, SemanticShift
from src.db.crud import create_document, save_nlp_data_to_db
from src.query.defaults import seed_defaults
from src.query import engine as qe
from src.analysis import semantic


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def corpus(db):
    """DE-документ с Gymnasium в трех контекстах + AT-документ со спорт-контекстом."""
    doc_de = create_document(db, "de.txt", country="DE", external_code="DE-01")
    doc_at = create_document(db, "at.txt", country="AT", external_code="AT-01")

    def fake_nlp(sentences):
        return {"sentences": [
            {"sent_id": i, "tokens": [
                {"word": w, "lemma": lem, "pos": pos} for w, lem, pos in s]}
            for i, s in enumerate(sentences)
        ]}

    save_nlp_data_to_db(db, doc_de.id, fake_nlp([
        # школа: маркеры schule/abitur -> правило DE
        [("Das", "der", "DET"), ("Gymnasium", "Gymnasium", "NOUN"),
         ("ist", "sein", "VERB"), ("eine", "ein", "DET"), ("Schule", "Schule", "NOUN")],
        # зал: маркер Geräte -> правило AT (в DE-доке тоже может быть, но маркер один)
        [("Im", "in", "ADP"), ("Gymnasium", "Gymnasium", "NOUN"),
         ("stehen", "stehen", "VERB"), ("neue", "neu", "ADJ"), ("Geräte", "Gerät", "NOUN")],
        # спорный: ни одного маркера
        [("Wir", "wir", "PRON"), ("diskutierten", "diskutieren", "VERB"),
         ("über", "über", "ADP"), ("das", "der", "DET"), ("Gymnasium", "Gymnasium", "NOUN")],
    ]))
    save_nlp_data_to_db(db, doc_at.id, fake_nlp([
        [("Das", "der", "DET"), ("Gymnasium", "Gymnasium", "NOUN"),
         ("im", "in", "ADP"), ("Sportzentrum", "Sportzentrum", "NOUN"),
         ("öffnet", "öffnen", "VERB")],  # sport - не точное вхождение 'sport'? 'sportzentrum' содержит 'sport'
    ]))
    return doc_de, doc_at


def _seed_shifts(db):
    db.add(SemanticShift(word="Gymnasium", country="DE",
                         meaning="тип средней школы",
                         collocations=json.dumps(["schule", "abitur"])))
    db.add(SemanticShift(word="Gymnasium", country="AT",
                         meaning="спортивный зал",
                         collocations=json.dumps(["sport", "geräte"])))
    db.commit()


def test_seed_includes_p7_and_shifts(db):
    counts = seed_defaults(db)
    from src.db.models import QueryParameter
    param = db.query(QueryParameter).filter(QueryParameter.code == "P7").first()
    assert param is not None and param.query_type == "SEMANTIC_SHIFT"
    assert counts["semantic_shifts"] >= 6
    # идемпотентность повторного сидинга
    again = seed_defaults(db)
    assert again["semantic_shifts"] == 0


def test_rules_classify_confident_and_pending(db, corpus):
    _seed_shifts(db)
    param = qe.QueryParameter(code="T-P7", name="тест P7",
                              query_type="SEMANTIC_SHIFT", markers="[]")
    db.add(param)
    db.commit()

    res = qe.run_parameter(db, param)
    assert res["hits"] == 4  # три вхождения в DE + одно в AT

    hits = db.query(qe.Hit).filter(qe.Hit.parameter_id == param.id).all()
    resolutions = sorted(h.resolution for h in hits)
    # DE+schule -> rule; DE+geräte -> rule(AT); DE без маркеров -> llm_pending;
    # AT с 'sport' в Sportzentrum -> rule
    assert resolutions.count("rule") == 3
    assert resolutions.count("llm_pending") == 1

    pending = semantic.pending_hits(db, "T-P7")
    assert len(pending) == 1
    assert "diskutierten" in pending[0]["sentence"]


def test_disambiguate_single_batch_call(db, corpus):
    _seed_shifts(db)
    param = qe.QueryParameter(code="T-P7B", name="тест P7 пакет",
                              query_type="SEMANTIC_SHIFT", markers="[]")
    db.add(param)
    db.commit()
    qe.run_parameter(db, param)

    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        ids = [item["hit_id"] for item in semantic.pending_hits(db, "T-P7B")]
        return "\n".join(f"N={i}: DE" for i in ids)

    stats = semantic.disambiguate_pending(db, "T-P7B", llm_call=fake_llm)
    assert len(calls) == 1                      # ровно один вызов LLM на весь пакет
    assert stats["resolved"] == stats["total"] == 1
    hit = db.query(qe.Hit).filter(qe.Hit.parameter_id == param.id,
                                  qe.Hit.resolution == "llm").first()
    assert hit is not None and ":DE=" in hit.matched_marker


def test_parse_disambiguation_response_variants():
    answer = "N=12: AT\nN=13: unknown\nкакой-то мусор\nN=14: de\n"
    verdicts = semantic.parse_disambiguation_response(answer)
    assert verdicts == {12: "AT", 13: "unknown", 14: "DE"}


def test_prompt_contains_all_pending_once(db, corpus):
    _seed_shifts(db)
    param = qe.QueryParameter(code="T-P7C", name="тест P7 промпт",
                              query_type="SEMANTIC_SHIFT", markers="[]")
    db.add(param)
    db.commit()
    qe.run_parameter(db, param)
    pending = semantic.pending_hits(db, "T-P7C")
    rules = semantic.load_rules(db)
    prompt = semantic.build_disambiguation_prompt(pending, rules)
    for item in pending:
        assert f"N={item['hit_id']}" in prompt
    assert "Gymnasium" in prompt
