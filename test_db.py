import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db.session import SessionLocal
from src.db.models import Base


def test_connection():
    db = SessionLocal()
    try:
        # При первом запуске создаем таблицы, если их еще нет.
        Base.metadata.create_all(bind=db.get_bind())

        from src.db.models import Document
        new_doc = Document(filename="mein_erstes_buch.pdf", language="de")
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        print(f"Успех! Документ '{new_doc.filename}' сохранен в БД. Его ID: {new_doc.id}")
        return 0
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(test_connection())
