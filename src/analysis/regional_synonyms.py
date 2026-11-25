from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Callable

import numpy as np

from src.analysis.compare import find_unique_lemmas

ALLOWED_POS = {"NOUN", "PROPN", "VERB", "ADJ"}


def normalize_ortho(word: str) -> str:
    return (
        word.lower()
        .replace("ß", "ss")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
    )


def detect_ortho_pairs(words_a: list[str], words_b: list[str]) -> list[dict[str, Any]]:
    norm_b = {normalize_ortho(w): w for w in words_b}
    pairs: list[dict[str, Any]] = []
    for wa in words_a:
        na = normalize_ortho(wa)
        wb = norm_b.get(na)
        if wb and wa.lower() != wb.lower():
            pairs.append({
                "kind": "orthographic",
                "word_a": wa,
                "word_b": wb,
                "confidence": "ORTHOGRAPHIC",
                "cos": 1.0,
                "margin": 0.0,
                "mutual": True,
            })
    return pairs


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def build_lemma_records_from_text(nlp: Any, text: str) -> dict[str, dict[str, Any]]:
    sentences = split_sentences(text)
    counts: Counter[str] = Counter()
    contexts: dict[str, str] = {}
    pos_map: dict[str, str] = {}

    for idx, sent in enumerate(sentences):
        doc = nlp(sent)
        window = " ".join(sentences[max(0, idx - 1) : min(len(sentences), idx + 2)])
        for tok in doc:
            if tok.is_alpha and tok.pos_ in ALLOWED_POS and len(tok.lemma_) > 1:
                lemma = tok.lemma_.lower()
                counts[lemma] += 1
                contexts.setdefault(lemma, window)
                pos_map.setdefault(lemma, tok.pos_)

    return {
        lemma: {
            "lemma": lemma,
            "pos": pos_map[lemma],
            "freq": counts[lemma],
            "context": contexts[lemma],
        }
        for lemma in counts
    }


def _format_context_prompt(lemma: str, meta: dict[str, Any]) -> str:
    pos = meta.get("pos") or "TERM"
    ctx = meta.get("context") or lemma
    return f"{lemma} ({pos}): {ctx}"


def rank_semantic_candidates(
    embedder: Any,
    records_a: dict[str, dict[str, Any]],
    records_b: dict[str, dict[str, Any]],
    *,
    llm_ratio: float = 0.05,
    min_llm_items: int = 3,
    rare_share: float = 0.25,
) -> dict[str, Any]:
    diff = find_unique_lemmas(records_a, records_b)
    uniq_a = diff["unique_A"]
    uniq_b = diff["unique_B"]
    total_uniq = len(uniq_a) + len(uniq_b)

    ortho_pairs = detect_ortho_pairs(uniq_a, uniq_b)
    ortho_a = {p["word_a"] for p in ortho_pairs}
    ortho_b = {p["word_b"] for p in ortho_pairs}

    cand_a = [w for w in uniq_a if w not in ortho_a]
    cand_b = [w for w in uniq_b if w not in ortho_b]

    if not cand_a or not cand_b or total_uniq == 0:
        return {
            "total_unique": total_uniq,
            "orthographic": ortho_pairs,
            "llm_pool": [],
            "deferred_pool": [],
        }

    prompts_a = [_format_context_prompt(w, records_a[w]) for w in cand_a]
    prompts_b = [_format_context_prompt(w, records_b[w]) for w in cand_b]

    emb_a = embedder.encode(prompts_a, normalize_embeddings=True, show_progress_bar=False)
    emb_b = embedder.encode(prompts_b, normalize_embeddings=True, show_progress_bar=False)

    sim = np.asarray(emb_a) @ np.asarray(emb_b).T
    best_a_for_b = np.argmax(sim, axis=0)

    vector_pairs: list[dict[str, Any]] = []
    matched_b: set[int] = set()

    for i, wa in enumerate(cand_a):
        order = np.argsort(sim[i])[::-1]
        j1 = int(order[0])
        s1 = float(sim[i, j1])
        s2 = float(sim[i, int(order[1])]) if len(order) > 1 else 0.0
        margin = round(s1 - s2, 4)
        mutual = bool(int(best_a_for_b[j1]) == i)

        if s1 >= 0.62 or (mutual and s1 >= 0.56 and margin >= 0.03):
            conf = "HIGH"
        elif s1 >= 0.50:
            conf = "MEDIUM"
        else:
            conf = "LOW"

        matched_b.add(j1)
        vector_pairs.append({
            "kind": "vector_pair",
            "word_a": wa,
            "word_b": cand_b[j1],
            "cos": round(s1, 4),
            "margin": margin,
            "mutual": mutual,
            "confidence": conf,
            "context_a": records_a[wa].get("context", ""),
            "context_b": records_b[cand_b[j1]].get("context", ""),
        })

    rare_probes: list[dict[str, Any]] = []
    for j, wb in enumerate(cand_b):
        freq_b = int(records_b[wb].get("freq", 1))
        if j not in matched_b or freq_b == 1:
            top_i = int(np.argmax(sim[:, j]))
            rare_probes.append({
                "kind": "rare_probe",
                "word": wb,
                "nearest_in_a": cand_a[top_i],
                "cos": round(float(sim[top_i, j]), 4),
                "freq": freq_b,
                "confidence": "RARE_PROBE",
                "context": records_b[wb].get("context", ""),
            })

    conf_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    vector_pairs.sort(
        key=lambda x: (
            0 if x.get("mutual") else 1,
            conf_rank[x["confidence"]],
            -x["cos"],
            -x["margin"],
        )
    )

    budget = max(min_llm_items, math.ceil(total_uniq * llm_ratio))
    rare_quota = int(round(budget * rare_share)) if (rare_probes and budget >= 4) else 0
    vector_quota = max(1, budget - rare_quota)

    selected_vector = vector_pairs[:vector_quota]
    used_words = {
        w
        for item in selected_vector
        for w in (item.get("word_a"), item.get("word_b"))
        if w
    }
    filtered_rare = [item for item in rare_probes if item.get("word") not in used_words]
    filtered_rare.sort(key=lambda x: (x["freq"], -x["cos"]))

    selected_rare = filtered_rare[:rare_quota]
    remaining_rare = filtered_rare[rare_quota:]

    deferred_pool = [
        {**item, "confidence": "DEFERRED"}
        for item in (vector_pairs[vector_quota:] + remaining_rare)
    ]

    return {
        "total_unique": total_uniq,
        "llm_budget": budget,
        "orthographic": ortho_pairs,
        "llm_pool": selected_vector + selected_rare,
        "deferred_pool": deferred_pool,
    }


def verify_candidates_with_llm(
    pair_label: str,
    items: list[dict[str, Any]],
    llm_completer: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    if not items:
        return {"pair": pair_label, "verified": [], "raw": ""}

    prompt = (
        "Ты лингвистический эксперт по региональным вариантам немецкого языка (DE / AT / CH). "
        "Проверь элементы (пары кандидатов с контекстами ±1 предложение или редкие слова-зонды). "
        "Отличи истинные смысловые/региональные эквиваленты от случайного тематического соседства. "
        "Верни строго валидный JSON-массив объектов с полями: "
        "word_a (или word), word_b (или null), is_equivalent (bool), relation_type, explanation_ru."
    )
    user_payload = json.dumps({"pair": pair_label, "items": items}, ensure_ascii=False)
    caller = llm_completer or complete_once
    raw = caller(f"{prompt}\n\nДанные:\n{user_payload}")

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = []

    return {
        "pair": pair_label,
        "verified": parsed if isinstance(parsed, list) else [],
        "raw": raw,
    }
