from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks
import shutil
import os
import uuid
import sys

# Добавляем пути
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.parser.reader import extract_and_normalize
from src.nlp.processor import process_text
from src.index.indexer import build_index
from src.db.session import SessionLocal
from src.db.crud import create_document, save_nlp_data_to_db, get_index_from_db

app = FastAPI(title="Lingva-Analyze API")

tasks_db = {}
os.makedirs("data/raw", exist_ok=True)

def process_document_background(task_id: str, file_path: str, filename: str):
    """Фоновая задача, которая теперь сохраняет всё в базу данных."""
    # Открываем сессию подключения к PostgreSQL
    db = SessionLocal()
    try:
        tasks_db[task_id] = "извлечение текста..."
        text = extract_and_normalize(file_path)
        
        tasks_db[task_id] = "создание записи в БД..."
        doc = create_document(db, filename=filename)
        
        tasks_db[task_id] = "nlp анализ (это может занять время)..."
        nlp_data = process_text(text)
        
        tasks_db[task_id] = "построение индекса..."
        index_data = build_index(doc.id, nlp_data["sentences"])
        
        tasks_db[task_id] = "сохранение в БД (предложения, токены, индекс)..."
        save_nlp_data_to_db(db, doc.id, nlp_data, index_data)
        
        tasks_db[task_id] = "готово"
        print(f"✅ Задача {task_id} завершена! Документ сохранен в БД под ID: {doc.id}")
        
    except Exception as e:
        db.rollback()
        tasks_db[task_id] = f"ошибка: {str(e)}"
        print(f"❌ Ошибка в задаче {task_id}: {e}")
    finally:
        # Обязательно закрываем соединение, чтобы не «повесить» базу
        db.close()

@app.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    country: str = Form(default="unknown"),
    doc_type: str = Form(default="unknown")
):
    file_path = f"data/raw/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    task_id = str(uuid.uuid4())
    tasks_db[task_id] = "в очереди"
    
    # Отправляем в фон (передаем имя файла для БД)
    background_tasks.add_task(process_document_background, task_id, file_path, file.filename)
    
    return {
        "task_id": task_id,
        "message": "Файл загружен. Обработка идет в фоне. Результат будет сохранен в БД."
    }

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    status = tasks_db.get(task_id, "Задача не найдена")
    return {"task_id": task_id, "status": status}

@app.get("/index/{doc_id}")
async def get_index(doc_id: int):
    """Эндпоинт для проверки того, что индекс реально летит в БД."""
    db = SessionLocal()
    try:
        index_data = get_index_from_db(db, doc_id)
        if not index_data:
            return {"error": f"Индекс для документа с ID {doc_id} не найден."}
        return {
            "doc_id": doc_id, 
            "unique_words_count": len(index_data), 
            "index_data": index_data
        }
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)