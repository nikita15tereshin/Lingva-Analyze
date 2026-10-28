"""Идемпотентность синка словарей (Этап 1).

Покрывает фиксы validator.load_entries / approve_entries:
- повторный sync одного источника не падает на IntegrityError;
- дубликаты внутри одного прогона парсера схлопываются;
- approved-статьи переживают повторный sync и не перезаписываются;
- load_entries возвращает корректную статистику inserted/updated/skipped;
- approve_entries переносит статьи в regional_dictionary без дублей.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from src.db.models import Base, DictionaryEntry, RegionalWord
from src.dictionaries.fetchers import DictEntry
from src.dictionaries.validator import approve_entries, load_entries


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def entries(pairs):
    return [DictEntry(term=t, definition=d, region=r, source_key="")
            for t, d, r in pairs]


SOURCE = "at_police_glossar"


def test_first_load_inserts_all(db):
    batch = entries([("Marille", "Aprikose", "AT"),
                     ("Jänner", "erster Monat", "AT"),
                     ("Billett", "Fahrkarte", "CH")])
    stats = load_entries(db, batch, SOURCE, None)
    assert stats["inserted"] == 3
    assert stats["updated"] == 0
    assert db.query(DictionaryEntry).count() == 3


def test_reload_same_source_is_idempotent(db):
    batch = entries([("Marille", "Aprikose", "AT"),
                     ("Jänner", "erster Monat", "AT")])
    load_entries(db, batch, SOURCE, None)
    # второй запуск того же списка — классический сценарий duplicate key
    stats2 = load_entries(db, batch, SOURCE, None)
    assert db.query(DictionaryEntry).count() == 2
    assert stats2["inserted"] == 2 or stats2["updated"] == 2
    assert stats2["skipped"] == 0


def test_duplicates_within_one_batch_are_collapsed(db):
    batch = entries([("Marille", "Aprikose", "AT"),
                     ("Marille", "Aprikose (дубль из таблицы)", "AT")])
    stats = load_entries(db, batch, SOURCE, None)
    assert stats["skipped"] == 1
    assert db.query(DictionaryEntry).count() == 1


def test_definition_update_survives_reload(db):
    load_entries(db, entries([("Marille", "старое значение", "AT")]),
                 SOURCE, None)
    load_entries(db, entries([("Marille", "новое значение", "AT")]),
                 SOURCE, None)
    row = db.query(DictionaryEntry).one()
    assert row.definition == "новое значение"


def test_approved_rows_not_touched_by_resync(db):
    load_entries(db, entries([("Marille", "Aprikose", "AT")]), SOURCE, None)
    assert approve_entries(db, source_key=SOURCE) == 1
    # источник снова отдаёт эту статью — approved-строка должна остаться как есть
    load_entries(db, entries([("Marille", "Abgeänderter Text", "AT")]),
                 SOURCE, None)
    row = db.query(DictionaryEntry).filter_by(term="Marille").one()
    assert row.status == "approved"
    assert row.definition == "Aprikose"
    # и в рабочий словарь не добавилось копий
    assert db.query(RegionalWord).filter_by(lemma="Marille").count() == 1


def test_approve_twice_does_not_duplicate_regional_words(db):
    load_entries(db, entries([("Jänner", "Monat", "AT"),
                              ("Parlamenter", "Hose", "AT")]),
                 SOURCE, None)
    first = approve_entries(db, source_key=SOURCE)
    assert first == 2
    second = approve_entries(db, source_key=SOURCE)
    assert second == 0  # pending-строк больше нет
    assert db.query(RegionalWord).count() == 2


def test_concurrent_approve_of_overlapping_pairs(db):
    """Два процесса подтверждают пересекающиеся леммы: без IntegrityError."""
    load_entries(db, entries([("Fiaker", "Kutsche", "AT")]), SOURCE, None)
    db.add(DictionaryEntry(term="Fiaker", definition="Zweispänner",
                           region="AT", source_key="other_src",
                           status="pending"))
    db.commit()
    # оба аппрувят одну и ту же пару (Fiaker, AT)
    n1 = approve_entries(db, source_key=SOURCE)
    n2 = approve_entries(db, source_key="other_src")
    assert n1 + n2 == 1  # ровно одна реальная вставка в regional_dictionary
    assert db.query(RegionalWord).filter_by(lemma="Fiaker").count() == 1


def test_rejected_rows_still_land_in_staging(db):
    """Отбраковка по формату не блокирует загрузку остальных статей."""
    batch = entries([("Marille", "Aprikose", "AT"),
                     ("Polizei", "Behörde", "AT")])  # германизм при валидации AT
    stats = load_entries(db, batch, SOURCE, "exclude_de_base")
    assert stats["by_status"].get("rejected_germanism") == 1
    assert stats["by_status"].get("pending") == 1
    assert db.query(DictionaryEntry).count() == 2
