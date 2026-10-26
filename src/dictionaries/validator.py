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


def load_entries(db: Session, entries: list[DictEntry], source_key: str,
                 spec_validate: str | None, replace_source: bool = True) -> dict:
    """Кладет результаты парсинга в staging. Повторный запуск того же
    источника заменяет его неотобранные статьи (идемпотентность обновления)."""
    de_terms = {r.lemma for r in db.query(RegionalWord).filter_by(region="DE")}
    stats = {"inserted": 0, "skipped": 0, "by_status": {}}

    if replace_source:
        db.query(DictionaryEntry).filter_by(
            source_key=source_key, status="pending"
        ).delete(synchronize_session=False)

    seen_in_batch: set[tuple[str, str]] = set()
    for e in entries:
        status, note = validate_entry(e, spec_validate, de_terms)
        key = (e.term.lower(), e.region)
        if key in seen_in_batch:
            stats["skipped"] += 1
            continue
        seen_in_batch.add(key)
        row = DictionaryEntry(
            term=e.term, definition=e.definition, region=e.region,
            source_key=source_key, status=status, note=note,
        )
        db.merge(row)  # unique(term, region, source_key) — повтор не дублирует
        stats["inserted"] += 1
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
    db.commit()
    return stats


def approve_entries(db: Session, ids: list[int] | None = None,
                    source_key: str | None = None) -> int:
    """Перенос подтвержденных статей из staging в рабочий regional_dictionary."""
    q = db.query(DictionaryEntry).filter(DictionaryEntry.status == "pending")
    if ids:
        q = q.filter(DictionaryEntry.id.in_(ids))
    if source_key:
        q = q.filter(DictionaryEntry.source_key == source_key)
    count = 0
    for row in q.all():
        exists = db.query(RegionalWord).filter_by(lemma=row.term, region=row.region).first()
        if not exists:
            db.add(RegionalWord(lemma=row.term, region=row.region,
                                standard_de=row.definition))
            count += 1
        row.status = "approved"
    db.commit()
    return count
