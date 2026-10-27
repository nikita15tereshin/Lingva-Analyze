"""Гибридный классификатор семантических сдвигов (пункт 3.2, P7).

Принцип: основную массу вхождений разбирает код (правила по колокациям),
LLM вызывается только для спорных случаев и получает сразу пакет таких
предложений одним запросом. Каждое попадание сохраняется в hits с полем
resolution: rule / llm_pending / llm.

Правила берутся из таблицы semantic_shifts: строка = одно значение слова
в одной стране + список колокаций-маркеров этого значения.

Третьей линией (между правилами и LLM) работает векторный дисамбигатор на
эмбеддингах spaCy (de_core_news_sm): каждое значение слова описывается
эталонными предложениями, спорное вхождение сравнивается с эталонами по
косинусной близости. Уверенные совпадения закрываются кодом (resolution =
vector), в LLM уходит только то, где векторы тоже не уверены. Отключается
фича переменной окружения SEMANTIC_USE_VECTORS=0.
"""

import json
import os

from sqlalchemy.orm import Session

from src.db.models import Document, Hit, QueryParameter, SemanticShift, Sentence

VECTOR_HIGH = 0.45   # ниже порога уверенности не опускаемся
VECTOR_MARGIN = 0.10  # отрыв лучшего эталона от второго должен быть заметным

_nlp = None


def _get_nlp():
    """Ленивая загрузка spaCy; кэш на процесс.

    Берется только tagger: он включает токенные векторы, а полный конвейер
    (лемматизатор/NER) здесь не нужен - леммы уже лежат в индексе.
    """
    global _nlp
    if _nlp is None:
        import spacy
        try:
            nlp = spacy.load("de_core_news_sm", disable=["parser", "ner", "lemmatizer"])
            # прогрев: без прогона pipeline has_vector у токенов False
            probe = nlp("test")
            if not any(t.has_vector for t in probe):
                _nlp = False
            else:
                _nlp = nlp
        except OSError:
            _nlp = False
    return _nlp or None


def vectors_available() -> bool:
    return (_get_nlp() is not None and
            os.getenv("SEMANTIC_USE_VECTORS", "1") != "0")


def _extract_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def load_rules(db: Session) -> dict[str, list[dict]]:
    """Правила по словам: {word: [{country, meaning, collocations, examples}, ...]}."""
    rules: dict[str, list[dict]] = {}
    for row in db.query(SemanticShift).all():
        rules.setdefault(row.word.lower(), []).append({
            "country": row.country,
            "meaning": row.meaning,
            "collocations": [c.lower() for c in _extract_json_list(row.collocations)],
            "examples": _extract_json_list(getattr(row, "examples", None)),
        })
    return rules


def _content_vector(nlp, text: str):
    """Вектор смысловых слов предложения с нормировкой по длине.

    Токенные векторы de_core_news_sm очень «размытые»: полное усреднение по
    всем словам дает косинусы 0.4-0.6 даже между несходными предложениями.
    Делим на (число токенов ** 1.5), чтобы длина текста не доминировала в
    близости, а направление задавали совпавшие смысловые слова.
    """
    import numpy as np
    content = {"NOUN", "VERB", "ADJ", "ADV", "PROPN"}
    doc = nlp(text)
    vectors = [t.vector for t in doc
               if not t.is_space and not t.is_punct and t.has_vector
               and (t.pos_ in content or t.pos == 0)]
    if not vectors:
        return None
    vec = np.mean(np.asarray(vectors), axis=0)
    return vec / (len(vectors) ** 1.5)


def classify_by_vectors(sentence_text: str, rules: list[dict]) -> tuple[str, dict | None]:
    """Векторная линия: близость к эталонным предложениям значений.

    Метрика - скорректированный косинус: из similarity вычитается средний
    уровень фонового сходства со всеми остальными эталонами. Дефолтные
    векторы spaCy дают 0.4-0.6 даже между несходными текстами, поэтому
    "сырой" порог был бы обманчив; поправка вычитает этот фон.

    Возвращает ("vector", r) при уверенном совпадении с одним значением,
    иначе ("llm_pending", None). Варианты одного и того же значения (разные
    страны/уточнения в скобках) склеиваются в один набор эталонов.
    """
    nlp = _get_nlp()
    candidates = [r for r in rules if r.get("examples")]
    if nlp is None or len(candidates) < 2:
        return "llm_pending", None
    try:
        import numpy as np
        sent_vec = _content_vector(nlp, sentence_text)
        if sent_vec is None:
            return "llm_pending", None
        base_labels: dict[str, dict] = {}
        for rule in candidates:
            label = rule["meaning"].split(" (")[0].strip()
            merged = base_labels.setdefault(
                label, {**rule, "examples": [], "meaning": label})
            merged["examples"].extend(rule["examples"])
        norm_sent = float(np.linalg.norm(sent_vec)) + 1e-9
        # все эталоны разом - для оценки фонового уровня сходства
        all_ex: list = []
        per_label: dict[str, list] = {}
        for label, rule in base_labels.items():
            vecs = [_content_vector(nlp, ex) for ex in rule["examples"]]
            vecs = [v for v in vecs if v is not None]
            per_label[label] = vecs
            all_ex.extend(vecs)
        if not all_ex or len(per_label) < 2:
            return "llm_pending", None
        background = sum(
            float(np.dot(sent_vec, v) / (norm_sent * np.linalg.norm(v) + 1e-9))
            for v in all_ex) / len(all_ex)
        scores: list[tuple[float, dict]] = []
        for label, rule in base_labels.items():
            if not per_label[label]:
                continue
            sim = max(float(np.dot(sent_vec, v) /
                            (norm_sent * np.linalg.norm(v) + 1e-9))
                      for v in per_label[label])
            scores.append((sim - background, rule))
        scores.sort(key=lambda s: s[0], reverse=True)
        best, second = scores[0], scores[1]
        if best[0] >= VECTOR_HIGH and best[0] - second[0] >= VECTOR_MARGIN:
            return "vector", best[1]
        return "llm_pending", None
    except Exception:
        # векторный слой не должен ронять основной прогон
        return "llm_pending", None


def classify_by_rules(sentence_text: str, word_lower: str,
                      doc_country: str | None, rules: list[dict]) -> tuple[str, dict | None]:
    """Вердикт кода без LLM.

    Возвращает (статус, правило):
    - ("rule", r)      - колокации однозначно указывают на значение r;
    - ("vector", r)    - колокации молчат, но векторное сравнение с эталонными
                         предложениями дало уверенный ответ;
    - ("llm_pending", None) - спорный случай, нужен LLM.
    """
    text_lower = sentence_text.lower()
    matched = []
    for rule in rules:
        if any(col in text_lower for col in rule["collocations"]):
            matched.append(rule)

    if len(matched) == 1:
        return "rule", matched[0]
    if len(matched) > 1:
        # несколько значений подтвердились: если одно совпадает со страной
        # документа - считаем это основным прочтением, иначе спорный случай
        if doc_country:
            same_country = [r for r in matched if r["country"] == doc_country]
            if len(same_country) == 1:
                return "rule", same_country[0]
        return "llm_pending", None
    # маркеров нет: если у слова ровно одно значение и оно совпадает со
    # страной документа - принимаем без LLM
    if doc_country:
        native = [r for r in rules if r["country"] == doc_country]
        if len(native) == 1 and len(rules) == 1:
            return "rule", native[0]
    # вторая линия кода: косинусная близость к эталонным предложениям
    return classify_by_vectors(sentence_text, rules)


def run_semantic_shift(db: Session, param: QueryParameter, doc_ids: list[int]) -> int:
    """Прогон P7: найти вхождения слов из справочника и разметить их правилами.

    Спорные случаи помечаются llm_pending; их забирает disambiguate_pending().
    """
    words = load_rules(db)
    if not words:
        return 0

    from src.query.engine import _occurrence_rows  # локальный импорт против цикла

    created = 0
    sentences = {
        s.id: s for s in db.query(Sentence).filter(Sentence.document_id.in_(doc_ids)).all()
    }
    countries = dict(
        db.query(Document.id, Document.country).filter(Document.id.in_(doc_ids)).all()
    )

    # Леммы в БД хранятся с исходным регистром (Gymnasium), ключи правил — в нижнем.
    rows = []
    seen_pairs = set()
    for sent_id, doc_id, lem, wf in _occurrence_rows(db, list(words.keys()), None, doc_ids):
        if (sent_id, lem.lower()) not in seen_pairs:
            seen_pairs.add((sent_id, lem.lower()))
            rows.append((sent_id, doc_id, lem, wf))

    for sentence_id, document_id, lemma, word_form in rows:
        sentence = sentences.get(sentence_id)
        if sentence is None:
            continue
        status, rule = classify_by_rules(
            sentence.text, lemma.lower(), countries.get(document_id), words[lemma.lower()]
        )
        # для векторного вердикта страна берется из разметки значения
        marker_country = rule["country"] if rule else None
        marker = (f"{lemma}:{marker_country}={rule['meaning']}"
                  if rule else f"{lemma}:спорный")
        db.add(Hit(
            parameter_id=param.id,
            document_id=document_id,
            sentence_id=sentence_id,
            matched_marker=marker,
            word_form=word_form,
            resolution=status,
        ))
        created += 1
    return created


def pending_hits(db: Session, parameter_code: str) -> list[dict]:
    """Спорные вхождения, требующие LLM-разбора."""
    rows = (
        db.query(Hit, Sentence.text, Document.country)
        .join(Sentence, Hit.sentence_id == Sentence.id)
        .join(Document, Hit.document_id == Document.id)
        .join(QueryParameter, Hit.parameter_id == QueryParameter.id)
        .filter(QueryParameter.code == parameter_code,
                Hit.resolution == "llm_pending")
        .order_by(Hit.id)
        .all()
    )
    return [
        {"hit_id": hit.id, "sentence": text, "document_country": country,
         "word_form": hit.word_form, "marker": hit.matched_marker}
        for hit, text, country in rows
    ]


def build_disambiguation_prompt(pending: list[dict], rules: dict[str, list[dict]]) -> str:
    """Один пакетный запрос ко всем спорным предложениям (экономия токенов)."""
    lines = []
    for item in pending:
        word = (item["marker"] or "").split(":")[0]
        variants = rules.get(word.lower(), [])
        variant_lines = "; ".join(
            f"[{r['country']}] {r['meaning']}" for r in variants) or "нет данных"
        lines.append(
            f"N={item['hit_id']} | слово: {word} | страна документа: "
            f"{item['document_country']} | значения: {variant_lines} | "
            f"предложение: {item['sentence']}"
        )
    numbered = "\n\n".join(lines)
    return (
        "Ты эксперт по региональным вариантам немецкого языка (DE - Германия, "
        "AT - Австрия, CH - Швейцария). Ниже перечислены предложения, в которых "
        "встречается слово с регионально различающимся значением. Для каждого "
        "определи, какое из указанных значений реализуется в контексте.\n\n"
        "Формат ответа: строго по одной строке вида 'N=<номер>: <код страны "
        "значения>' без пояснений. Если контекст не позволяет определить "
        "значение, ответь 'N=<номер>: unknown'.\n\n"
        f"{numbered}\n"
    )


def parse_disambiguation_response(text: str) -> dict[int, str]:
    """Разбор ответов LLM вида 'N=12: AT' в {hit_id: страна значения или unknown}."""
    result: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip().lower().replace("n=", "")
        if ":" not in line:
            continue
        num, _, value = line.partition(":")
        value = value.strip().rstrip(".")
        try:
            hit_id = int(num.strip())
        except ValueError:
            continue
        if value in ("de", "at", "ch"):
            result[hit_id] = value.upper()
        elif value:
            result[hit_id] = "unknown"
    return result


def disambiguate_pending(db: Session, parameter_code: str, llm_call=None) -> dict:
    """Дозбор спорных hits через LLM одним пакетом.

    llm_call(prompt) -> str можно передать извне (для тестов); по умолчанию
    берется настроенный провайдер из src.analysis.llm.
    """
    pending = pending_hits(db, parameter_code)
    stats = {"total": len(pending), "resolved": 0, "unknown": 0, "failed": 0}
    if not pending:
        return stats

    if llm_call is None:
        from src.analysis.llm import complete_once
        llm_call = complete_once

    rules = load_rules(db)
    prompt = build_disambiguation_prompt(pending, rules)
    try:
        answer = llm_call(prompt)
    except Exception:
        stats["failed"] = len(pending)
        return stats

    verdicts = parse_disambiguation_response(answer)
    by_id = {item["hit_id"]: item for item in pending}
    for hit_id, country in verdicts.items():
        hit = db.get(Hit, hit_id)
        if hit is None or hit.id not in by_id:
            continue
        if country == "unknown":
            stats["unknown"] += 1
            continue
        word = (hit.matched_marker or "").split(":")[0]
        meaning = next(
            (r["meaning"] for r in rules.get(word.lower(), []) if r["country"] == country),
            None)
        hit.matched_marker = f"{word}:{country}={meaning}" if meaning else f"{word}:{country}"
        hit.resolution = "llm"
        stats["resolved"] += 1

    stats["failed"] = len(pending) - stats["resolved"] - stats["unknown"]
    db.commit()
    return stats
