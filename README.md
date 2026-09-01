# Lingva-Analyze

Lingva-Analyze — микросервис для лингвистического анализа текстов на немецком языке. Проект автоматизирует извлечение текста, построение лексических индексов и поиск региональных семантических сдвигов с помощью LLM.

## Основные возможности

* **Парсинг:** Извлечение и нормализация текста из `.txt`, `.pdf`, `.docx`.


* **NLP:** Токенизация и лемматизация через `spaCy` (`de_core_news_sm`).


* **Хранение данных:** Сохранение структуры документа и лексического индекса в PostgreSQL.


* **Анализ:** Поиск уникальных лемм и их классификация по региональным словарям.


* **LLM-интеграция:** Потоковый семантический анализ через балансировщик с моделью `kimi-k3-free`.



## Технологический стек

* **Backend:** FastAPI, Python, Streamlit (UI).


* **База данных:** PostgreSQL, SQLAlchemy, Alembic.


* **NLP/ML:** spaCy, OpenAI API.


* **Инфраструктура:** Docker, Docker Compose.



## Структура проекта

* `src/api/` — FastAPI сервер.


* `src/ui/` — Streamlit интерфейс.


* `src/nlp/` — Лингвистическая обработка.


* `src/parser/` — Экстракция текста.


* `src/db/` — Модели БД и CRUD-операции.


* `src/analysis/` — Лексическое сравнение и LLM.



## Установка и запуск

**1. Зависимости и модели**

```bash
pip install -r requirements.txt
python -m spacy download de_core_news_sm

```

**2. База данных и миграции**

```bash
docker-compose up -d
alembic upgrade head
python src/db/seed_dictionary.py

```

**3. Запуск компонентов**

* **API:** `uvicorn src.api.main:app --reload`
* **UI:** `streamlit run src/ui/app.py`

## Технический долг

В текущей реализации UI (Streamlit) напрямую обращается к БД и выполняет NLP-задачи в основном потоке, минуя API-слой. Хардкод-ключи LLM в `src/analysis/llm.py` требуют выноса в переменные окружения.
