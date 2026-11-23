from openai import OpenAI

from src.analysis.settings import load_raw


def _client_and_model() -> tuple[OpenAI, str]:
    """Собирает клиент из текущих настроек (вкладка LLM / env-дефолты)."""
    settings = load_raw()
    client = OpenAI(
        base_url=settings["base_url"] or None,
        api_key=settings["api_key"] or "missing-key",
    )
    return client, settings["model"]


def _not_configured_message() -> str:
    return (
        "Ключ LLM не задан. Откройте вкладку LLM в интерфейсе и сохраните "
        "провайдера с API-ключом либо задайте переменную окружения LLM_API_KEY."
    )


def analyze_semantic_context_stream(word: str, sentence: str, expected_region: str):
    """
    Генератор, который отправляет запрос в LLM и возвращает ответ чанками (потоком).
    Провайдер, модель и ключ берутся из настроек (вкладка LLM), значения по
    умолчанию - из переменных окружения.
    """
    settings = load_raw()
    if not settings["api_key"]:
        yield _not_configured_message()
        return

    prompt = f"""
    Ты эксперт по региональным вариантам немецкого языка (Германия, Австрия, Швейцария).
    
    Проанализируй использование слова '{word}' в следующем предложении:
    "{sentence}"
    
    Задачи:
    1. Подтверди, характерно ли использование этого слова в данном контексте для региона '{expected_region}'.
    2. Укажи стандартный немецкий эквивалент (Bundesdeutsches Hochdeutsch).
    3. Если здесь наблюдается семантический сдвиг, подробно объясни его.
    
    Ответь кратко, академическим стилем, подходящим для лингвистической диссертации.
    """
    
    messages = [
        {"role": "system", "content": "You are an intelligent linguistic assistant, please reply concisely."},
        {"role": "user", "content": prompt}
    ]
    
    print(f"[LLM Stream] Запрос для слова: '{word}' отправлен...")
    
    try:
        client, model = _client_and_model()
        # Включаем stream=True и убираем таймаут, чтобы ждать столько, сколько нужно
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            stream=True 
        )
        
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                
    except Exception as e:
        print(f"[LLM Stream] Ошибка: {str(e)}")
        yield f"\n\nОшибка при обращении к нейросети: {str(e)}"


def complete_once(prompt: str) -> str:
    """Одиночный (не потоковый) запрос к настроенному провайдеру.

    Используется гибридным классификатором P7: спорные случаи уходят в LLM
    одним пакетом, ответ нужен целиком для разбора построчных вердиктов.
    """
    settings = load_raw()
    if not settings["api_key"]:
        raise RuntimeError(_not_configured_message())
    client, model = _client_and_model()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "You are an intelligent linguistic assistant. "
                        "Follow the required output format exactly."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return response.choices[0].message.content or ""


def analyze_matrix_parameter_stream(parameter_code: str, max_examples: int = 40):
    """Пункт 4.3 ТЗ: сравнительный анализ по результатам прогона параметра.

    Собирает количественную статистику (4.1) и контексты (4.2) из БД,
    формирует академический промпт и стримит ответ LLM чанками.
    """
    from src.db.session import SessionLocal
    from src.query import engine as query_engine

    settings = load_raw()
    if not settings["api_key"]:
        yield _not_configured_message()
        return

    db = SessionLocal()
    try:
        by_country = query_engine.statistics_by_country(db, parameter_code)
        by_marker = query_engine.statistics_by_marker(db, parameter_code)
        contexts = query_engine.hits_with_context(db, parameter_code, limit=max_examples)
    finally:
        db.close()

    if not contexts and not by_country:
        yield (f"По параметру {parameter_code} нет попаданий. "
               "Сначала прогоните его по корпусу.")
        return

    stats_lines = "\n".join(
        f"- {row['country']}: {row['hits']} попаданий" for row in by_country)
    marker_lines = "\n".join(
        f"- {row['marker']}: {row['hits']}" for row in by_marker[:30])
    example_lines = "\n".join(
        f"[{row['code'] or row['document']} / {row['country']}] {row['sentence']} "
        f"(маркер: {row['word_form'] or row['marker']})"
        for row in contexts)

    prompt = f"""
Ты эксперт по региональным вариантам немецкого языка (Германия DE, Австрия AT,
Швейцария CH). Проведи сравнительный анализ материала по параметру
"{parameter_code}" матрицы параметров диссертационного исследования.

Количественные данные (попадания по странам):
{stats_lines or 'нет данных'}

Разбивка по маркерам:
{marker_lines or 'нет данных'}

Примеры контекстов (официально-деловые документы и стенограммы выступлений):
{example_lines or 'нет примеров'}

Задачи:
1. Опиши, как распределены показатели между странами и насколько различия значимы.
2. Приведи характерные примеры из контекстов с пояснениями.
3. Сформулируй выводы для раздела диссертации в академическом стиле.
Ответ дай на русском языке, структурированно, без воды.
"""

    messages = [
        {"role": "system",
         "content": "You are an intelligent linguistic assistant, please reply concisely."},
        {"role": "user", "content": prompt},
    ]

    print(f"[LLM Stream] Запрос по параметру '{parameter_code}' отправлен...")

    try:
        client, model = _client_and_model()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            stream=True,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        print(f"[LLM Stream] Ошибка: {str(e)}")
        yield f"\n\nОшибка при обращении к нейросети: {str(e)}"

def _sample_document_text(sentences: list[str], max_chars: int = 10000) -> str:
    full_text = " ".join(sentences)
    if len(full_text) <= max_chars:
        return full_text
    part = max_chars // 3
    head = full_text[:part]
    mid_start = max(0, (len(full_text) - part) // 2)
    mid = full_text[mid_start:mid_start + part]
    tail = full_text[-part:]
    return (
        head
        + " [...] [СЕРЕДИНА ДОКУМЕНТА] [...] "
        + mid
        + " [...] [КОНЦОВКА ДОКУМЕНТА] [...] "
        + tail
    )


def _parse_json_response(raw: str) -> dict:
    import json
    import re

    cleaned = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.S)
    if m:
        cleaned = m.group(1).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"raw_response": raw}


def analyze_document_qualitative(
    db,
    doc_id: int,
    llm_call=None,
    max_chars: int = 10000,
) -> dict:
    # Пункт 6 ТЗ: структура, тональность, главные угрозы, отношение к РФ/КНР, стилистика
    from src.db.models import Document, Sentence

    doc = db.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"Документ с ID {doc_id} не найден")

    rows = (
        db.query(Sentence.text)
        .filter(Sentence.document_id == doc_id)
        .order_by(Sentence.sentence_number)
        .all()
    )
    sentences = [r[0] for r in rows if r[0]]
    if not sentences:
        raise ValueError(f"В документе ID {doc_id} нет проиндексированных предложений")

    excerpt = _sample_document_text(sentences, max_chars=max_chars)
    prompt = (
        "Ты эксперт по политической лингвистике и анализу официально-деловых "
        "документов немецкоязычных стран (DE/AT/CH). "
        f"Проанализируй документ: {doc.filename} (страна: {doc.country or "не указана"}, "
        f"всего предложений в корпусе: {len(sentences)}). "
        "Верни СТРОГО валидный JSON без пояснений вне JSON со следующими ключами: "
        "1) structure (объект: chapters, estimated_scope, visuals_and_tables), "
        "2) tone (объект: main_focus, emotionality, summary), "
        "3) main_threats (список строк: главные угрозы на первом плане — шпионаж, терроризм, экстремизм и т.д.), "
        "4) geopolitical_attitude (объект: russia, china, other_countries), "
        "5) stylistic_notes (объект: metaphors, historical_references). "
        "Текст документа (фрагмент): " \
        "IMPORTANT: Write all descriptive string values in the JSON strictly in Russian. Keep all JSON keys strictly in English exactly as specified in the schema. Preserve original German wording for direct quotes, chapter titles, and metaphors from the text (adding a brief Russian explanation if helpful)." + excerpt
    )

    caller = llm_call or complete_once
    raw = caller(prompt)
    parsed = _parse_json_response(raw)

    return {
        "doc_id": doc.id,
        "filename": doc.filename,
        "country": doc.country,
        "sentences_count": len(sentences),
        "analysis": parsed,
    }
