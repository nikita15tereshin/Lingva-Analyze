"""Движок запросов матрицы параметров (пункты 3.0, P1-P9 ТЗ).

Параметр задается данными в таблице query_parameters, а не кодом:
добавление нового критерия = новая строка в справочнике. Результаты
прогона складываются в таблицу hits (параметр, документ, предложение,
сработавший маркер, словоформа) — оттуда берутся и количественная
статистика (4.1), и контексты для качественного анализа (4.2).
"""

import json
import re

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from src.db.models import (
    Document,
    Hit,
    LexicalPair,
    QueryParameter,
    RegionalWord,
    Sentence,
    Token,
    LexicalIndex,
)

QUERY_TYPES = ("LEMMA_SET", "LEMMA_AND", "WORD_REGEX", "TEXT_REGEX",
               "LEXICAL_PAIR", "DICTIONARY", "FREQUENCY_RANGE", "SEMANTIC_SHIFT")


def parse_markers(param: QueryParameter) -> list[dict]:
    """Маркеры параметра: {"lemma": str, "pos": str|None}; pos обязателен только для LEMMA_*."""
    if not param.markers:
        return []
    markers = []
    for item in json.loads(param.markers):
        if isinstance(item, str):
            markers.append({"lemma": item, "pos": None})
        else:
            markers.append({"lemma": item.get("lemma"), "pos": item.get("pos")})
    return markers


def _document_scope(db: Session, document_ids, countries) -> list[int]:
    q = db.query(Document.id)
    if document_ids:
        q = q.filter(Document.id.in_(document_ids))
    if countries:
        q = q.filter(Document.country.in_(countries))
    return [row[0] for row in q.all()]


def _clear_previous_hits(db: Session, param_id: int, doc_ids: list[int]):
    db.query(Hit).filter(
        Hit.parameter_id == param_id,
        Hit.document_id.in_(doc_ids),
    ).delete(synchronize_session=False)


def _occurrence_rows(db: Session, lemmas: list[str], pos: str | None, doc_ids: list[int]):
    """Вхождения лемм: (sentence_id, document_id, lemma, word_form)."""
    q = (
        db.query(LexicalIndex.sentence_id, Sentence.document_id, Token.lemma, LexicalIndex.word_form)
        .join(Token, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(Token.lemma.in_(lemmas), Sentence.document_id.in_(doc_ids))
    )
    if pos:
        q = q.filter(Token.pos == pos)
    return q.all()


def run_lemma_set(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Любое из слов набора (P1 должныствование, P3 модальность)."""
    created = 0
    for marker in parse_markers(param):
        for sentence_id, document_id, lemma, word_form in _occurrence_rows(
            db, [marker["lemma"]], marker["pos"], doc_ids
        ):
            db.add(Hit(
                parameter_id=param.id,
                document_id=document_id,
                sentence_id=sentence_id,
                matched_marker=lemma,
                word_form=word_form,
            ))
            created += 1
    return created


def run_lemma_and(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Все слова одновременно в одном предложении (пункт 3.0: wohl + man)."""
    markers = parse_markers(param)
    if len(markers) < 2:
        raise ValueError("Для типа LEMMA_AND нужно минимум два маркера")

    # предложения, содержащие каждое из слов; берем пересечение множеств
    common = None
    for marker in markers:
        li = aliased(LexicalIndex)
        tok = aliased(Token)
        sq = (
            db.query(li.sentence_id)
            .join(tok, li.token_id == tok.id)
            .join(Sentence, li.sentence_id == Sentence.id)
            .filter(tok.lemma == marker["lemma"], Sentence.document_id.in_(doc_ids))
        )
        if marker["pos"]:
            sq = sq.filter(tok.pos == marker["pos"])
        ids = {row[0] for row in sq.all()}
        common = ids if common is None else (common & ids)

    created = 0
    marker_text = ", ".join(m["lemma"] for m in markers)
    # словоформы маркеров для подсветки в контексте (берем первую совпавшую форму)
    forms_by_sentence: dict[int, str | None] = {}
    if common:
        lemmas = [m["lemma"] for m in markers]
        rows = _occurrence_rows(db, lemmas, None, doc_ids)
        for sentence_id, _document_id, lemma, word_form in rows:
            if sentence_id in common and forms_by_sentence.get(sentence_id) is None:
                forms_by_sentence[sentence_id] = word_form
    for sentence_id in sorted(common or ()):
        sentence = db.get(Sentence, sentence_id)
        db.add(Hit(
            parameter_id=param.id,
            document_id=sentence.document_id,
            sentence_id=sentence_id,
            matched_marker=marker_text,
            word_form=forms_by_sentence.get(sentence_id),
        ))
        created += 1
    return created


def run_word_regex(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Регулярка по словоформе (P9 суффикс -in, 3.4 часть слова/корень)."""
    patterns = [m["lemma"] for m in parse_markers(param)]
    rows = (
        db.query(LexicalIndex.sentence_id, Sentence.document_id, LexicalIndex.word_form)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(Sentence.document_id.in_(doc_ids))
        .all()
    )
    compiled = [(p, re.compile(p, re.IGNORECASE)) for p in patterns]

    created = 0
    for sentence_id, document_id, word_form in rows:
        if not word_form:
            continue
        for pattern, rx in compiled:
            if rx.search(word_form):
                db.add(Hit(
                    parameter_id=param.id,
                    document_id=document_id,
                    sentence_id=sentence_id,
                    matched_marker=pattern,
                    word_form=word_form,
                ))
                created += 1
                break
    return created


def run_text_regex(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Регулярка по тексту предложения (P4 ссылки на НПА, прикол Б цифры/годы)."""
    patterns = [m["lemma"] for m in parse_markers(param)]
    sentences = (
        db.query(Sentence.id, Sentence.document_id, Sentence.text)
        .filter(Sentence.document_id.in_(doc_ids))
        .all()
    )

    created = 0
    for pattern in patterns:
        rx = re.compile(pattern)
        for sentence_id, document_id, text in sentences:
            match = rx.search(text or "")
            if match:
                db.add(Hit(
                    parameter_id=param.id,
                    document_id=document_id,
                    sentence_id=sentence_id,
                    matched_marker=pattern,
                    word_form=match.group(0),
                ))
                created += 1
    return created


def run_lexical_pair(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Лексические замены (3.1, P8): ищем все члены пар из справочника lexical_pairs."""
    lemmas = []
    for pair in db.query(LexicalPair).all():
        lemmas.extend(w for w in (pair.de_word, pair.at_word, pair.ch_word) if w)
    if not lemmas:
        return 0

    created = 0
    for sentence_id, document_id, lemma, word_form in _occurrence_rows(db, lemmas, None, doc_ids):
        db.add(Hit(
            parameter_id=param.id,
            document_id=document_id,
            sentence_id=sentence_id,
            matched_marker=lemma,
            word_form=word_form,
        ))
        created += 1
    return created


def run_dictionary(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Австрицизмы/гельветизмы (P5/P6): вхождения слов из regional_dictionary."""
    regional = db.query(RegionalWord).all()
    if not regional:
        return 0
    region_map = {w.lemma: w.region for w in regional}

    created = 0
    for sentence_id, document_id, lemma, word_form in _occurrence_rows(
        db, list(region_map.keys()), None, doc_ids
    ):
        db.add(Hit(
            parameter_id=param.id,
            document_id=document_id,
            sentence_id=sentence_id,
            matched_marker=f"{region_map.get(lemma, '?')}:{lemma}",
            word_form=word_form,
        ))
        created += 1
    return created


def run_frequency_range(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Отдельный прогон (прикол А): леммы с частотой в документе от min до max.

    Маркеры задаются параметрами, не словами: {"min": 1, "max": 5}.
    Каждое такое слово фиксируется одним hit'ом на документ; word_form —
    любая встретившаяся форма, matched_marker — 'лемма x N'.
    """
    cfg = json.loads(param.markers) if param.markers else {}
    lo = int(cfg.get("min", 1))
    hi = int(cfg.get("max", 5))

    # LexicalIndex.document_id — виртуальное поле, в БД документ зашит в sentences
    doc_id_col = Sentence.document_id
    rows = (
        db.query(doc_id_col, Token.lemma, func.count(LexicalIndex.id),
                 func.min(LexicalIndex.word_form))
        .join(Token, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(doc_id_col.in_(doc_ids))
        .group_by(doc_id_col, Token.lemma)
        .having(func.count(LexicalIndex.id).between(lo, hi))
        .all()
    )

    created = 0
    for document_id, lemma, count, form in rows:
        db.add(Hit(
            parameter_id=param.id,
            document_id=document_id,
            sentence_id=None,
            matched_marker=f"{lemma} x {count}",
            word_form=form or lemma,
        ))
        created += 1
    return created


RUNNERS = {
    "LEMMA_SET": run_lemma_set,
    "LEMMA_AND": run_lemma_and,
    "WORD_REGEX": run_word_regex,
    "TEXT_REGEX": run_text_regex,
    "LEXICAL_PAIR": run_lexical_pair,
    "DICTIONARY": run_dictionary,
    "FREQUENCY_RANGE": run_frequency_range,
}


def _runners_with_semantic() -> dict:
    """SEMANTIC_SHIFT подключается лениво, чтобы не создавать цикл импортов."""
    if "SEMANTIC_SHIFT" not in RUNNERS:
        from src.analysis.semantic import run_semantic_shift
        RUNNERS["SEMANTIC_SHIFT"] = run_semantic_shift
    return RUNNERS


def run_parameter(db: Session, param: QueryParameter,
                  document_ids: list[int] | None = None,
                  countries: list[str] | None = None) -> dict:
    """Прогон параметра по области корпуса. Повторный запуск заменяет старые hits."""
    runners = _runners_with_semantic()
    if param.query_type not in runners:
        raise ValueError(f"Неизвестный тип запроса: {param.query_type}")

    doc_ids = _document_scope(db, document_ids, countries)
    if not doc_ids:
        return {"parameter": param.code, "documents": 0, "hits": 0}

    _clear_previous_hits(db, param.id, doc_ids)
    created = runners[param.query_type](db, param, doc_ids)
    db.commit()

    return {"parameter": param.code, "documents": len(doc_ids), "hits": created}


def statistics_by_country(db: Session, parameter_code: str) -> list[dict]:
    """Количественный показатель (4.1): вхождения параметра по странам."""
    rows = (
        db.query(Document.country, func.count(Hit.id))
        .join(Hit, Hit.document_id == Document.id)
        .join(QueryParameter, Hit.parameter_id == QueryParameter.id)
        .filter(QueryParameter.code == parameter_code)
        .group_by(Document.country)
        .all()
    )
    return [{"country": country or "не указана", "hits": count} for country, count in rows]


def statistics_by_marker(db: Session, parameter_code: str) -> list[dict]:
    """Разбивка попаданий по маркерам (например, сколько раз попалось Bundeswehr)."""
    rows = (
        db.query(Hit.matched_marker, func.count(Hit.id))
        .join(QueryParameter, Hit.parameter_id == QueryParameter.id)
        .filter(QueryParameter.code == parameter_code)
        .group_by(Hit.matched_marker)
        .order_by(func.count(Hit.id).desc())
        .all()
    )
    return [{"marker": marker, "hits": count} for marker, count in rows]


def resolution_stats(db: Session, parameter_code: str) -> dict:
    """Сколько вхождений P7 закрыто правилами, векторами, LLM и осталось спорных."""
    rows = (
        db.query(Hit.resolution, func.count(Hit.id))
        .join(QueryParameter, Hit.parameter_id == QueryParameter.id)
        .filter(QueryParameter.code == parameter_code)
        .group_by(Hit.resolution)
        .all()
    )
    stats = {"rule": 0, "vector": 0, "llm": 0, "llm_pending": 0, "other": 0}
    total = 0
    for resolution, count in rows:
        total += count
        stats[resolution if resolution in stats else "other"] += count
    stats["total"] = total
    resolved = stats["rule"] + stats["vector"] + stats["llm"]
    stats["code_share"] = round(resolved / total, 3) if total else None
    return stats


def corpus_statistics(db: Session) -> list[dict]:
    """Сводка 4.1 по всему корпусу: попаданий каждого параметра по странам."""
    rows = (
        db.query(QueryParameter.code, Document.country, func.count(Hit.id))
        .join(Hit, Hit.parameter_id == QueryParameter.id)
        .outerjoin(Document, Hit.document_id == Document.id)
        .group_by(QueryParameter.code, Document.country)
        .order_by(QueryParameter.code)
        .all()
    )
    return [{"parameter": code, "country": country or "не указана", "hits": count}
            for code, country, count in rows]


def hits_with_context(db: Session, parameter_code: str, limit: int = 200) -> list[dict]:
    """Качественный материал (4.2): предложение целиком + сработавшая форма."""
    rows = (
        db.query(Hit, Sentence.text, Document.filename, Document.external_code, Document.country)
        .join(Sentence, Hit.sentence_id == Sentence.id)
        .join(Document, Hit.document_id == Document.id)
        .join(QueryParameter, Hit.parameter_id == QueryParameter.id)
        .filter(QueryParameter.code == parameter_code)
        .order_by(Hit.id)
        .limit(limit)
        .all()
    )
    return [
        {
            "document": filename,
            "code": external_code,
            "country": country,
            "sentence": text,
            "marker": hit.matched_marker,
            "word_form": hit.word_form,
            "resolution": hit.resolution,
        }
        for hit, text, filename, external_code, country in rows
    ]
