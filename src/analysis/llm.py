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