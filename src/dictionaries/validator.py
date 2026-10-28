"""Валидация и загрузка словарных статей в staging-таблицу.

Правила валидации:
1) термин — одна лексема или короткая словосочетательная единица;
2) для AT-источников с validate=exclude_de_base термины, совпадающие с
   обычной немецкой лексикой (DE-словари + стоп-лист), отбрасываются со
   статусом rejected_germanism — это фильтр германизмов из полицейского
   глоссария (пункт "100% на валидацию" в ТЗ);
3) все остальное попадает в dictionary_entries со статусом pending и
   импортируется в regional_dictionary только после подтверждения через
   UI/API (approve).
"""

import re
import unicodedata

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db.models import DictionaryEntry, RegionalWord
from src.dictionaries.fetchers import DictEntry

WORD_RE = re.compile(r"^[\wÄÖÜäöüß][\wÄÖÜäöüß\-/. ]{0,79}$")

# Базовая общеупотребительная лексика, которая не может быть австрицизмом
# по смыслу полицейских/юридических текстов. Список расширяется вручную.
COMMON_DE = {
    "polizei", "beamter", "dienst", "gesetz", "verordnung", "strafe",
    "delikt", "tater", "opfer", "zeugen", "einsatz", "fahndung",
    "ermittlung", "antrag", "bescheid", "verfahren", "gericht",
    "staatsanwaltschaft", "verfassung", "sicherheit", "schutz",
    "kriminalitat", "gewalt", "drogen", "brand", "unfall", "fahrt",
    "wagen", "fahrzeug", "waffe", "diebstahl", "betrug", "mord",
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ss", "\u00df").replace("\u00df", "ss")


def is_common_german(term: str, de_terms: set[str]) -> bool:
    t = _fold(term)
    return t in de_terms or t in {_fold(w) for w in COMMON_DE}


def validate_entry(entry: DictEntry, spec_validate: str | None,
                   de_terms: set[str]) -> tuple[str, str | None]:
    """Возвращает (status, note)."""
    term = entry.term.strip()
    if not term or not WORD_RE.match(term):
        return "rejected_format", "термин не проходит форматный фильтр"
    if len(entry.definition.strip()) < 3:
        return "rejected_format", "пустое определение"
    if entry.region == "AT" and spec_validate == "exclude_de_base":
        if is_common_german(term, de_terms):
            return "rejected_germanism", "совпадает с общеупотребительной нормой"
    return "pending", None


def _upsert_insert(engine: Engine, values: list[dict]):
    """INSERT ... ON CONFLICT (term, region, source_key) DO NOTHING.

    Для PostgreSQL и SQLite используется диалектный on_conflict_do_nothing;
    для прочих диалектов — обычный insert с последующей фильтрацией
    IntegrityError на уровне вызывающего кода не требуется (в проекте БД — PG).
    """
    dialect = engine.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(DictionaryEntry.__table__).values(values)
        return stmt.on_conflict_do_nothing(
            index_elements=["term", "region", "source_key"]
        )
    if dialect == "sqlite":
        stmt = sqlite_insert(DictionaryEntry.__table__).values(values)
        return stmt.on_conflict_do_nothing(
            index_elements=["term", "region", "source_key"]
        )
    return DictionaryEntry.__table__.insert().values(values)


def load_entries(db: Session, entries: list[DictEntry], source_key: str,
                 spec_validate: str | None, replace_source: bool = True) -> dict:
    """Кладет результаты парсинга в staging идемпотентно.

    Повторный синк того же источника обновляет definition/status/note у уже
    известных статей, но никогда не трогает статьи со статусом approved
    (они могли быть отредактированы вручную) и не создает дубликатов по
    уникальному ключу (term, region, source_key). Запись идет батчем через
    ON CONFLICT DO NOTHING, поэтому одновременная вставка из параллельного
    процесса не роняет синхронизацию на IntegrityError.
    """
    de_terms = {r.lemma for r in db.query(RegionalWord).filter_by(region="DE")}
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "by_status": {}}

    rows: dict[tuple[str, str], dict] = {}
    for e in entries:
        status, note = validate_entry(e, spec_validate, de_terms)
        key = (e.term.strip(), e.region)
        if key in rows:  # дубликаты внутри одного прогона парсера
            stats["skipped"] += 1
            continue
        rows[key] = {
            "term": e.term.strip(), "definition": e.definition.strip(),
            "region": e.region, "source_key": source_key,
            "status": status, "note": note,
        }
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

    if not rows:
        db.commit()
        return stats

    value_list = list(rows.values())
    if replace_source:
        # Строки, которые будут перезаписаны upsert'ом (все, кроме approved),
        # удаляем до вставки: так чистятся устаревшие статьи источника.
        db.query(DictionaryEntry).filter(
            DictionaryEntry.source_key == source_key,
            DictionaryEntry.status != "approved",
            DictionaryEntry.term.in_([v["term"] for v in value_list]),
            DictionaryEntry.region.in_([v["region"] for v in value_list]),
        ).delete(synchronize_session=False)
        db.flush()

    result = db.execute(_upsert_insert(db.get_bind(), value_list))
    inserted = result.rowcount if result.rowcount is not None else len(value_list)
    stats["inserted"] = max(inserted, 0)
    stats["updated"] = max(len(value_list) - stats["inserted"], 0)
    db.commit()
    return stats


def approve_entries(db: Session, ids: list[int] | None = None,
                    source_key: str | None = None) -> int:
    """Перенос подтвержденных статей из staging в рабочий regional_dictionary.

    Уникальность (lemma, region) гарантируется частичным уникальным индексом
    uq_regional_word_lemma_region: проверка SELECT + db.add здесь небезопасна
    при конкурентном аппруве, поэтому вставка идет через ON CONFLICT DO NOTHING,
    а количество реально добавленных строк берется из rowcount.
    """
    q = db.query(DictionaryEntry).filter(DictionaryEntry.status == "pending")
    if ids:
        q = q.filter(DictionaryEntry.id.in_(ids))
    if source_key:
        q = q.filter(DictionaryEntry.source_key == source_key)
    rows = q.all()
    if not rows:
        return 0

    values = [{"lemma": r.term, "region": r.region, "standard_de": r.definition}
              for r in rows]
    dialect = db.get_bind().dialect.name
    if dialect in ("postgresql", "sqlite"):
        ins = (pg_insert if dialect == "postgresql" else sqlite_insert)(
            RegionalWord.__table__
        ).values(values)
        ins = ins.on_conflict_do_nothing(index_elements=["lemma", "region"])
        result = db.execute(ins)
        count = result.rowcount or 0
    else:  # pragma: no cover - резервный путь для тестовой среды без upsert
        existing = {
            (l, g) for l, g in db.query(RegionalWord.lemma, RegionalWord.region).all()
        }
        count = 0
        for v in values:
            if (v["lemma"], v["region"]) not in existing:
                db.add(RegionalWord(**v))
                existing.add((v["lemma"], v["region"]))
                count += 1
    for r in rows:
        r.status = "approved"
    db.commit()
    return count
