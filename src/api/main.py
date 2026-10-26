import io
import json
import os
import shutil
import sys
import uuid

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.parser.reader import extract_and_normalize
from src.nlp.processor import process_text
from src.db.session import SessionLocal
from src.db.crud import (
    create_document,
    save_nlp_data_to_db,
    get_document_index_from_db,
    get_frequency_table,
)
from src.db.models import QueryParameter
from src.query import engine as query_engine
from src.query.defaults import seed_defaults

app = FastAPI(title="Lingva-Analyze API")

VALID_COUNTRIES = {"DE", "AT", "CH"}
os.makedirs("data/raw", exist_ok=True)


# Статусы фоновых задач держим в памяти процесса (см. рекомендацию в AUDIT.md
# о переносе в таблицу БД/очередь при переходе на несколько воркеров).
TASK_STATUSES: dict[str, str] = {}


def set_task_status(task_id: str, status: str):
    TASK_STATUSES[task_id] = status
    print(f"[task {task_id}] {status}")


def process_document_background(
    task_id: str, file_path: str, filename: str,
    country: str | None, doc_type: str | None, external_code: str | None,
):
    """Фоновая обработка: извлечение текста, NLP, сохранение в БД."""
    db = SessionLocal()
    try:
        set_task_status(task_id, "извлечение текста...")
        text = extract_and_normalize(file_path, filename)

        set_task_status(task_id, "создание записи в БД...")
        doc = create_document(
            db, filename=filename,
            country=country, doc_type=doc_type, external_code=external_code,
        )

        set_task_status(task_id, "NLP-анализ...")
        nlp_data = process_text(text)

        set_task_status(task_id, "сохранение в БД (предложения, токены, индекс)...")
        save_nlp_data_to_db(db, doc.id, nlp_data)

        set_task_status(task_id, f"готово (document_id={doc.id})")
    except Exception as e:
        db.rollback()
        set_task_status(task_id, f"ошибка: {e}")
    finally:
        db.close()


@app.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    country: str = Form(default=""),
    doc_type: str = Form(default=""),
    external_code: str = Form(default=""),
):
    country = country.strip().upper() or None
    if country and country not in VALID_COUNTRIES:
        raise HTTPException(400, f"Страна должна быть одной из {sorted(VALID_COUNTRIES)}")

    safe_name = os.path.basename(file.filename)
    file_path = os.path.join("data/raw", safe_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    task_id = str(uuid.uuid4())
    set_task_status(task_id, "в очереди")

    background_tasks.add_task(
        process_document_background,
        task_id, file_path, safe_name,
        country, doc_type.strip() or None, external_code.strip() or None,
    )

    return {
        "task_id": task_id,
        "message": "Файл загружен. Обработка идет в фоне. Результат будет сохранен в БД.",
    }


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    if task_id not in TASK_STATUSES:
        return {"task_id": task_id, "status": "Задача не найдена"}
    return {"task_id": task_id, "status": TASK_STATUSES[task_id]}


@app.get("/index/{doc_id}")
async def get_index(doc_id: int):
    """Восстановленный из БД лексический индекс документа."""
    db = SessionLocal()
    try:
        index_data = get_document_index_from_db(db, doc_id)
        if not index_data:
            raise HTTPException(404, f"Индекс для документа с ID {doc_id} не найден.")
        return {
            "doc_id": doc_id,
            "unique_words_count": len(index_data),
            "index_data": index_data,
        }
    finally:
        db.close()


@app.get("/frequency/{doc_id}")
async def get_frequency(doc_id: int, max_count: int | None = None):
    """Частотный словарь лемм; max_count<=5 — фильтр 'редкие слова' (прикол А)."""
    db = SessionLocal()
    try:
        table = get_frequency_table(db, doc_id)
        if max_count is not None:
            table = [row for row in table if row["count"] <= max_count]
        return {"doc_id": doc_id, "entries": len(table), "frequency": table}
    finally:
        db.close()


@app.get("/parameters")
async def list_parameters():
    db = SessionLocal()
    try:
        rows = db.query(QueryParameter).order_by(QueryParameter.code).all()
        return [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "query_type": p.query_type,
                "markers": json.loads(p.markers) if p.markers else [],
            }
            for p in rows
        ]
    finally:
        db.close()


@app.post("/parameters/seed")
async def seed_parameters():
    db = SessionLocal()
    try:
        return seed_defaults(db)
    finally:
        db.close()


@app.post("/run/{parameter_code}")
async def run_parameter_endpoint(
    parameter_code: str,
    countries: str = Form(default=""),
    document_ids: str = Form(default=""),
):
    """Прогон параметра матрицы по корпусу (или выбранной его части)."""
    country_list = [c.strip().upper() for c in countries.split(",") if c.strip()] or None
    doc_list = [int(d) for d in document_ids.split(",") if d.strip()] or None

    db = SessionLocal()
    try:
        param = db.query(QueryParameter).filter(QueryParameter.code == parameter_code).first()
        if not param:
            raise HTTPException(404, f"Параметр {parameter_code} не найден. Выполните POST /parameters/seed.")
        result = query_engine.run_parameter(db, param, doc_list, country_list)
        return result
    finally:
        db.close()


@app.get("/statistics/{parameter_code}")
async def statistics_endpoint(parameter_code: str):
    db = SessionLocal()
    try:
        return {
            "by_country": query_engine.statistics_by_country(db, parameter_code),
            "by_marker": query_engine.statistics_by_marker(db, parameter_code),
            "resolution": query_engine.resolution_stats(db, parameter_code),
        }
    finally:
        db.close()


class SemanticShiftPayload(BaseModel):
    word: str
    country: str
    meaning: str
    collocations: list[str] = []
    examples: list[str] = []
    concept: str | None = None
    note: str | None = None


@app.get("/semantic-shifts")
async def list_semantic_shifts():
    """Справочник омонимов для P7 (word + country -> значение и маркеры)."""
    from src.db.models import SemanticShift
    db = SessionLocal()
    try:
        rows = db.query(SemanticShift).order_by(
            SemanticShift.word, SemanticShift.country).all()
        return [
            {
                "id": r.id,
                "word": r.word,
                "country": r.country,
                "meaning": r.meaning,
                "collocations": json.loads(r.collocations) if r.collocations else [],
                "examples": json.loads(r.examples) if r.examples else [],
                "concept": r.concept,
                "note": r.note,
            }
            for r in rows
        ]
    finally:
        db.close()


@app.post("/semantic-shifts")
async def add_semantic_shift(payload: SemanticShiftPayload):
    """Добавить или обновить значение омонима (идемпотентно по word+country+meaning)."""
    from src.db.models import SemanticShift
    if payload.country.upper() not in ("DE", "AT", "CH"):
        raise HTTPException(400, "Страна должна быть DE, AT или CH")
    db = SessionLocal()
    try:
        row = db.query(SemanticShift).filter(
            SemanticShift.word == payload.word,
            SemanticShift.country == payload.country.upper(),
            SemanticShift.meaning == payload.meaning).first()
        if row is None:
            row = SemanticShift(word=payload.word, country=payload.country.upper(),
                                meaning=payload.meaning)
            db.add(row)
        row.collocations = json.dumps(payload.collocations, ensure_ascii=False)
        row.examples = json.dumps(payload.examples, ensure_ascii=False)
        row.concept = payload.concept
        row.note = payload.note
        db.commit()
        return {"id": row.id, "word": row.word, "country": row.country,
                "updated": True}
    finally:
        db.close()


@app.delete("/semantic-shifts/{shift_id}")
async def delete_semantic_shift(shift_id: int):
    from src.db.models import SemanticShift
    db = SessionLocal()
    try:
        row = db.get(SemanticShift, shift_id)
        if row is None:
            raise HTTPException(404, "Запись не найдена")
        db.delete(row)
        db.commit()
        return {"deleted": shift_id}
    finally:
        db.close()


@app.get("/pending/{parameter_code}")
async def pending_disambiguation(parameter_code: str):
    """Спорные вхождения P7, которые правила не разметили (требуют LLM)."""
    from src.analysis.semantic import pending_hits
    db = SessionLocal()
    try:
        rows = pending_hits(db, parameter_code)
        return {"total": len(rows), "items": rows[:200]}
    finally:
        db.close()


@app.post("/disambiguate/{parameter_code}")
async def disambiguate_endpoint(parameter_code: str):
    """Один пакетный LLM-запрос по всем спорным вхождениям параметра."""
    from src.analysis.semantic import disambiguate_pending
    db = SessionLocal()
    try:
        return disambiguate_pending(db, parameter_code)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@app.get("/export/{parameter_code}.csv")
async def export_csv(parameter_code: str):
    """Выгрузка всех попаданий параметра (документ, код, предложение, форма)."""
    db = SessionLocal()
    try:
        rows = query_engine.hits_with_context(db, parameter_code)
    finally:
        db.close()

    def generate():
        yield "\ufeff"  # BOM для корректной кириллицы/умлаутов в Excel
        writer = io.StringIO()
        import csv as _csv
        w = _csv.writer(writer, delimiter=";", lineterminator="\r\n")
        w.writerow(["Документ", "Код", "Страна", "Маркер", "Словоформа", "Предложение"])
        first = True
        for r in rows:
            w.writerow([r["document"], r["code"], r["country"], r["marker"], r["word_form"], r["sentence"]])
            if first:
                first = False
            chunk = writer.getvalue()
            writer.seek(0)
            writer.truncate(0)
            yield chunk.encode("utf-8")

    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{parameter_code}.csv"'})


@app.get("/statistics")
async def statistics_all():
    """Сводка 4.1: попадания каждого параметра по странам."""
    db = SessionLocal()
    try:
        return {"by_parameter_country": query_engine.corpus_statistics(db)}
    finally:
        db.close()


@app.get("/export/all.csv")
async def export_all_csv():
    """Один CSV по всем прогнанным параметрам (колонка parameter)."""
    from src.query.export import export_workbook_csv

    db = SessionLocal()
    try:
        data = export_workbook_csv(db)
    finally:
        db.close()
    if not data:
        return JSONResponse(status_code=404,
                            content={"detail": "Нет попаданий ни по одному параметру"})
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="matrix_all.csv"'})


@app.get("/export/workbook.xlsx")
async def export_workbook_xlsx():
    """Сводная книга XLSX для передачи в LLM (пункт 4.3 ТЗ)."""
    from src.query.export import export_workbook_xlsx as build_xlsx

    db = SessionLocal()
    try:
        data = build_xlsx(db)
    finally:
        db.close()
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="matrix_workbook.xlsx"'})


# ------------------------------------------------------------------ словари

@app.get("/dictionary/sources")
async def dictionary_sources():
    """Реестр сайтов-словарей с последним статусом синхронизации."""
    from src.db.models import DictionarySource
    db = SessionLocal()
    try:
        rows = db.query(DictionarySource).order_by(DictionarySource.key).all()
        return [
            {
                "key": r.key, "title": r.title, "url": r.url, "region": r.region,
                "extraction": r.extraction, "headless": bool(r.headless),
                "enabled": bool(r.enabled), "last_sync_at": r.last_sync_at.isoformat() if r.last_sync_at else None,
                "last_status": r.last_status, "last_error": r.last_error,
                "entry_count": r.entry_count,
            }
            for r in rows
        ]
    finally:
        db.close()


@app.post("/dictionary/sync/{source_key}")
async def sync_dictionary_source(source_key: str):
    """Обновить один словарь-сайт (парсинг -> валидация -> staging)."""
    from src.dictionaries.sync import sync_registry, sync_source
    db = SessionLocal()
    try:
        sync_registry(db)
        try:
            return sync_source(db, source_key)
        except ValueError as e:
            raise HTTPException(404, str(e))
    finally:
        db.close()


@app.post("/dictionary/sync_all")
async def sync_all_dictionaries():
    """Кнопка 'обновить данные по всем словарям'."""
    from src.dictionaries.sync import sync_all
    db = SessionLocal()
    try:
        return {"results": sync_all(db)}
    finally:
        db.close()


@app.get("/dictionary/entries")
async def dictionary_entries(source_key: str = "", status: str = "", limit: int = 500):
    """Просмотр staging-статей перед подтверждением."""
    from src.db.models import DictionaryEntry
    db = SessionLocal()
    try:
        q = db.query(DictionaryEntry)
        if source_key:
            q = q.filter(DictionaryEntry.source_key == source_key)
        if status:
            q = q.filter(DictionaryEntry.status == status)
        rows = q.order_by(DictionaryEntry.id).limit(limit).all()
        return [
            {"id": r.id, "term": r.term, "definition": r.definition,
             "region": r.region, "source_key": r.source_key,
             "status": r.status, "note": r.note}
            for r in rows
        ]
    finally:
        db.close()


class LLMSettingsPayload(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


@app.get("/llm/settings")
async def llm_settings_get():
    """Текущие настройки LLM без ключа (только маска и признак наличия)."""
    from src.analysis.settings import public_view
    return public_view()


@app.post("/llm/settings")
async def llm_settings_save(payload: LLMSettingsPayload):
    """Сохраняет провайдера/ключ/модель. Пустой или замаскированный ключ не перезаписывает."""
    from src.analysis.settings import save, PROVIDERS
    if payload.provider and payload.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Неизвестный провайдер")
    save(
        provider=payload.provider,
        api_key=payload.api_key,
        model=payload.model,
        base_url=payload.base_url,
    )
    from src.analysis.settings import public_view
    return public_view()


@app.post("/dictionary/approve")
async def approve_dictionary_entries(payload: dict):
    """Подтвердить статьи: ids=[...] или source_key='...' (все pending источника)."""
    from src.dictionaries.validator import approve_entries
    db = SessionLocal()
    try:
        moved = approve_entries(db, payload.get("ids"), payload.get("source_key"))
        return {"moved_to_regional_dictionary": moved}
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
