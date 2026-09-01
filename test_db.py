from src.db.session import SessionLocal
from src.db.models import Document

def test_connection():
    # Открываем сессию (подключение)
    db = SessionLocal()
    
    try:
        # Создаем тестовую запись
        new_doc = Document(filename="mein_erstes_buch.pdf", language="de")
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        print(f"✅ Успех! Документ '{new_doc.filename}' сохранен в БД. Его ID: {new_doc.id}")
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_connection()