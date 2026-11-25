from __future__ import annotations

import json
import re
from sqlalchemy.orm import Session

from src.analysis.llm import _parse_json_response, complete_once
from src.db.models import ComparisonResult, LexicalPair, RegionalWord, SemanticShift

_ZWSP = "\u200b"
_EDGE_RE = re.compile(r"^[^A-Za-zÄÖÜäöüß-]+|[^A-Za-zÄÖÜäöüß-]+$")
_WORD_RE = re.compile(r"^[A-Za-zÄÖÜäöüß]{3,}(?:-[A-Za-zÄÖÜäöüß]{2,})?$")


def _clean_term(val: str) -> str:
    return _EDGE_RE.sub("", (val or "").replace(_ZWSP, "")).strip("-")


def _is_clean_term(val: str) -> bool:
    return bool(_WORD_RE.match(_clean_term(val)))


def build_candidate_payload(res: dict, max_per_side: int = 10) -> list[dict]:
    payload: list[dict] = []
    sem = res.get("semantic_candidates") or {}

    if not sem.get("embedder_available"):
        for it in (res.get("unique_a_regional") or [])[:max_per_side]:
            lem = _clean_term(it.get("lemma", ""))
            if _is_clean_term(lem):
                payload.append({
                    "lemma_a": lem,
                    "lemma_b": "",
                    "region_hint": it.get("region", ""),
                    "context_a": " | ".join(it.get("contexts") or []),
                })
        for it in (res.get("unique_b_regional") or [])[:max_per_side]:
            lem = _clean_term(it.get("lemma", ""))
            if _is_clean_term(lem):
                payload.append({
                    "lemma_a": "",
                    "lemma_b": lem,
                    "region_hint": it.get("region", ""),
                    "context_b": " | ".join(it.get("contexts") or []),
                })
        if not payload:
            list_a = [
                {
                    "lemma_a": _clean_term(it.get("lemma", "")),
                    "lemma_b": "",
                    "flag": "FALLBACK_UNIQUE_A",
                    "context_a": " | ".join(it.get("contexts") or []),
                }
                for it in (res.get("unique_a_sample") or [])[:max_per_side]
                if _is_clean_term(it.get("lemma", ""))
            ]
            list_b = [
                {
                    "lemma_a": "",
                    "lemma_b": _clean_term(it.get("lemma", "")),
                    "flag": "FALLBACK_UNIQUE_B",
                    "context_b": " | ".join(it.get("contexts") or []),
                }
                for it in (res.get("unique_b_sample") or [])[:max_per_side]
                if _is_clean_term(it.get("lemma", ""))
            ]
            for i in range(max(len(list_a), len(list_b))):
                if i < len(list_a):
                    payload.append(list_a[i])
                if i < len(list_b):
                    payload.append(list_b[i])
        return payload

    for item in sem.get("orthographic") or []:
        payload.append({
            "lemma_a": _clean_term(item.get("word_a", "")),
            "lemma_b": _clean_term(item.get("word_b", "")),
            "flag": "ORTHOGRAPHIC",
            "cos": item.get("cos"),
        })

    for item in sem.get("llm_pool") or []:
        if item.get("kind") == "vector_pair":
            payload.append({
                "lemma_a": _clean_term(item.get("word_a", "")),
                "lemma_b": _clean_term(item.get("word_b", "")),
                "flag": item.get("confidence", ""),
                "cos": item.get("cos"),
                "context_a": item.get("context_a", ""),
                "context_b": item.get("context_b", ""),
            })
        else:
            payload.append({
                "lemma_a": _clean_term(item.get("word", "")),
                "lemma_b": _clean_term(item.get("nearest_in_a", "")),
                "flag": item.get("confidence", "RARE_PROBE"),
                "cos": item.get("cos"),
                "context": item.get("context", ""),
            })
    return payload


def verify_compare_candidates(candidates: list[dict], limit: int = 5) -> list[dict]:
    selected = candidates[:limit]
    if not selected:
        return []
    schema_lines = [
        "Ты эксперт по региональным вариантам немецкого языка (DE, AT, CH).",
        "Проанализируй кандидатов и верни ТОЛЬКО валидный JSON-объект с ключом items.",
        "Если среди кандидатов из документа A (lemma_a) и документа B (lemma_b) есть региональные эквиваленты одного понятия (например, Aprikose и Marille, Bundeswehr и Bundesheer), ОБЪЕДИНИ их в один объект с kind='lexical_pair', заполнив оба поля lemma_a и lemma_b.",
        "Каждый объект в items:",
        "- lemma_a: str",
        "- lemma_b: str",
        "- kind: lexical_pair | semantic_shift | regional_word | other",
        "- concept: str",
        "- country: DE | AT | CH | null",
        "- de_word: str | null",
        "- at_word: str | null",
        "- ch_word: str | null",
        "- meaning: str",
        "- confidence: float (0.0..1.0)",
        "- comment: str",
        "",
        "Кандидаты:",
        json.dumps(selected, ensure_ascii=False),
    ]
    prompt = "\n".join(schema_lines)
    raw = complete_once(prompt)
    parsed = _parse_json_response(raw)
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return [{"comment": json.dumps(parsed, ensure_ascii=False)}]


def save_verified_compare_items(db: Session, items: list[dict]) -> dict[str, int]:
    saved = {
        "comparison_results": 0,
        "lexical_pairs": 0,
        "semantic_shifts": 0,
        "regional_dictionary": 0,
    }
    for it in items:
        la = _clean_term(it.get("lemma_a") or "")
        lb = _clean_term(it.get("lemma_b") or "")
        if not la and not lb:
            continue
        try:
            conf = float(it.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        comment = (it.get("comment") or it.get("meaning") or "").strip()
        concept = (it.get("concept") or f"{la} / {lb}").strip()
        meaning = (it.get("meaning") or comment or concept).strip()
        kind = (it.get("kind") or "").strip()
        country = (it.get("country") or "").strip().upper()

        db.add(
            ComparisonResult(
                lemma_a=la or "-",
                lemma_b=lb or "-",
                confidence=conf,
                llm_comment=comment,
            )
        )
        saved["comparison_results"] += 1

        if kind == "lexical_pair":
            de_w = it.get("de_word") or la or None
            at_w = it.get("at_word") or lb or None
            ch_w = it.get("ch_word") or None
            dup = db.query(LexicalPair).filter(
                LexicalPair.concept == concept,
                LexicalPair.de_word == de_w,
                LexicalPair.at_word == at_w,
            ).first()
            if not dup:
                db.add(
                    LexicalPair(
                        concept=concept,
                        de_word=de_w,
                        at_word=at_w,
                        ch_word=ch_w,
                        note=comment or None,
                    )
                )
                saved["lexical_pairs"] += 1

        elif kind == "semantic_shift" and country in ("DE", "AT", "CH"):
            w = la or lb
            if w:
                dup = db.query(SemanticShift).filter(
                    SemanticShift.word == w,
                    SemanticShift.country == country,
                    SemanticShift.meaning == meaning,
                ).first()
                if not dup:
                    db.add(
                        SemanticShift(
                            word=w,
                            concept=concept,
                            country=country,
                            meaning=meaning,
                            note=comment or None,
                        )
                    )
                    saved["semantic_shifts"] += 1

        elif kind == "regional_word" and country in ("AT", "CH"):
            w = la or lb
            if w:
                dup = db.query(RegionalWord).filter(
                    RegionalWord.lemma == w,
                    RegionalWord.region == country,
                ).first()
                if not dup:
                    db.add(
                        RegionalWord(
                            lemma=w,
                            region=country,
                            standard_de=meaning or None,
                        )
                    )
                    saved["regional_dictionary"] += 1

    db.commit()
    return saved