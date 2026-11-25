# Сравнительный анализ двух документов (Этап 3).

import re
from sqlalchemy.orm import Session

from src.analysis.compare import find_unique_lemmas
from src.analysis.context import get_contexts_for_lemma
from src.analysis.regional_synonyms import rank_semantic_candidates
from src.db.crud import get_document_index_from_db
from src.db.models import DictionaryEntry, Document, RegionalWord

_EMBEDDER_CACHE = None
_EMBEDDER_LOADED = False


def _get_optional_embedder():
    global _EMBEDDER_CACHE, _EMBEDDER_LOADED
    if _EMBEDDER_LOADED:
        return _EMBEDDER_CACHE
    _EMBEDDER_LOADED = True
    try:
        from sentence_transformers import SentenceTransformer
        _EMBEDDER_CACHE = SentenceTransformer("BAAI/bge-m3")
    except Exception:
        _EMBEDDER_CACHE = None
    return _EMBEDDER_CACHE


def _build_lemma_records_from_db(
    db: Session,
    doc_id: int,
    unique_lemmas: list[str],
    index_map: dict,
    max_contexts: int = 2,
) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for lemma in unique_lemmas:
        positions = index_map.get(lemma) or []
        freq = max(1, len(positions))
        contexts = get_contexts_for_lemma(db, lemma, doc_id)
        sentences = [c.get("target_sentence", "").strip() for c in contexts[:max_contexts] if c.get("target_sentence")]
        records[lemma] = {
            "lemma": lemma,
            "pos": "TERM",
            "freq": freq,
            "context": " ".join(sentences) if sentences else lemma,
        }
    return records


def _build_semantic_candidates(
    db: Session,
    doc_a_id: int,
    doc_b_id: int,
    index_a: dict,
    index_b: dict,
    diff: dict,
) -> dict:
    empty = {
        "total_unique": len(diff["unique_A"]) + len(diff["unique_B"]),
        "llm_budget": 0,
        "orthographic": [],
        "llm_pool": [],
        "deferred_pool": [],
        "embedder_available": False,
    }
    embedder = _get_optional_embedder()
    if embedder is None:
        return empty

    records_a = _build_lemma_records_from_db(db, doc_a_id, diff["unique_A"], index_a)
    records_b = _build_lemma_records_from_db(db, doc_b_id, diff["unique_B"], index_b)
    ranked = rank_semantic_candidates(embedder, records_a, records_b)
    return {**ranked, "embedder_available": True}


def _load_approved_dictionary(db: Session) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in db.query(RegionalWord).all():
        key = row.lemma.strip().lower()
        if key:
            lookup[key] = {
                "region": row.region,
                "meaning": row.standard_de or "",
            }
    for row in db.query(DictionaryEntry).filter(DictionaryEntry.status == "approved").all():
        key = row.term.strip().lower()
        if key and key not in lookup:
            lookup[key] = {
                "region": row.region,
                "meaning": row.definition or "",
            }
    return lookup


def _enrich_unique_lemmas(
    db: Session,
    doc_id: int,
    unique_lemmas: list[str],
    dict_lookup: dict[str, dict],
    max_contexts: int = 5,
) -> list[dict]:
    items: list[dict] = []
    for lemma in unique_lemmas:
        info = dict_lookup.get(lemma.lower())
        if not info:
            continue
        contexts = get_contexts_for_lemma(db, lemma, doc_id)
        sentences = [c["target_sentence"] for c in contexts[:max_contexts]]
        items.append({
            "lemma": lemma,
            "region": info["region"],
            "meaning": info["meaning"],
            "contexts": sentences,
        })
    return items


def compare_documents(db: Session, doc_a_id: int, doc_b_id: int) -> dict:
    doc_a = db.get(Document, doc_a_id)
    if doc_a is None:
        raise ValueError(f"Документ A (id={doc_a_id}) не найден")
    doc_b = db.get(Document, doc_b_id)
    if doc_b is None:
        raise ValueError(f"Документ B (id={doc_b_id}) не найден")

    index_a = get_document_index_from_db(db, doc_a_id)
    index_b = get_document_index_from_db(db, doc_b_id)
    diff = find_unique_lemmas(index_a, index_b)

    dict_lookup = _load_approved_dictionary(db)

    def _sample_with_ctx(lemmas: list[str], doc_id: int, limit: int = 12) -> list[dict]:
        zwsp = "\u200b"
        out: list[dict] = []
        for lem in lemmas:
            w = re.sub(
                r"^[^A-Za-zÄÖÜäöüß-]+|[^A-Za-zÄÖÜäöüß-]+$",
                "",
                (lem or "").replace(zwsp, ""),
            ).strip("-")
            if re.match(r"^[A-Za-zÄÖÜäöüß]{3,}(?:-[A-Za-zÄÖÜäöüß]{2,})?$", w):
                ctxs = get_contexts_for_lemma(db, lem, doc_id)
                sentences = [c["target_sentence"] for c in ctxs[:2] if c.get("target_sentence")]
                out.append({"lemma": w, "contexts": sentences})
                if len(out) >= limit:
                    break
        return out

    return {
        "doc_a": {
            "id": doc_a.id,
            "filename": doc_a.filename,
            "country": doc_a.country,
            "external_code": doc_a.external_code,
        },
        "doc_b": {
            "id": doc_b.id,
            "filename": doc_b.filename,
            "country": doc_b.country,
            "external_code": doc_b.external_code,
        },
        "unique_a_total": len(diff["unique_A"]),
        "unique_b_total": len(diff["unique_B"]),
        "unique_a_regional": _enrich_unique_lemmas(db, doc_a_id, diff["unique_A"], dict_lookup),
        "unique_b_regional": _enrich_unique_lemmas(db, doc_b_id, diff["unique_B"], dict_lookup),
        "unique_a_sample": _sample_with_ctx(diff["unique_A"], doc_a_id),
        "unique_b_sample": _sample_with_ctx(diff["unique_B"], doc_b_id),
        "semantic_candidates": _build_semantic_candidates(db, doc_a_id, doc_b_id, index_a, index_b, diff),
    }