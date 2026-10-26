"""Оркестрация синхронизации словарных сайтов с БД.

sync_source(db, key) — один источник: fetch -> parse -> validate -> staging;
sync_all(db) — все включенные источники по реестру sources.SOURCES.

Модуль не тянет playwright-зависимости на уровне импорта: headless-режим
включается только для источников с headless=1 и корректно деградирует,
если браузер не установлен (источник помечается failed в справочнике).
"""

from datetime import datetime

from sqlalchemy.orm import Session

from src.db.models import DictionarySource
from src.dictionaries import fetchers
from src.dictionaries.sources import SOURCES
from src.dictionaries.validator import load_entries


def sync_registry(db: Session) -> int:
    """Синхронизирует справочник dictionary_sources с реестром SOURCES."""
    existing = {s.key: s for s in db.query(DictionarySource).all()}
    count = 0
    for spec in SOURCES:
        row = existing.get(spec.key)
        if row is None:
            row = DictionarySource(key=spec.key)
            db.add(row)
        row.title = spec.title
        row.url = spec.url
        row.region = spec.region
        row.extraction = spec.extraction
        row.headless = 1 if spec.headless else 0
        row.enabled = 1 if spec.enabled else 0
        row.validate = spec.validate
        count += 1
    db.commit()
    return count


def _mark(db: Session, key: str, status: str, error: str | None = None,
          entries: int | None = None):
    row = db.query(DictionarySource).filter_by(key=key).first()
    if row:
        row.last_sync_at = datetime.utcnow()
        row.last_status = status
        row.last_error = error[:2000] if error else None
        if entries is not None:
            row.entry_count = entries
        db.commit()


def sync_source(db: Session, key: str, force_headless: bool | None = None) -> dict:
    """Обновляет один источник. Возвращает сводку для UI/API."""
    spec = next((s for s in SOURCES if s.key == key), None)
    if spec is None:
        raise ValueError(f"Источник {key} не найден в реестре")
    try:
        entries = fetchers.extract_entries(spec, headless=force_headless)
    except ImportError as e:
        _mark(db, key, "failed_browser", str(e))
        return {"source": key, "ok": False,
                "error": f"не установлен браузер для headless-рендера: {e}"}
    except Exception as e:
        _mark(db, key, "failed", repr(e))
        return {"source": key, "ok": False, "error": repr(e)}

    stats = load_entries(db, entries, spec.key, spec.validate)
    _mark(db, key, "ok", None, stats["inserted"])
    return {"source": key, "ok": True, **stats}


def sync_all(db: Session) -> list[dict]:
    sync_registry(db)
    results = []
    for spec in SOURCES:
        if not spec.enabled:
            continue
        try:
            results.append(sync_source(db, spec.key))
        except ValueError as e:
            results.append({"source": spec.key, "ok": False, "error": str(e)})
    return results
