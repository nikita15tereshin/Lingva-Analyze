import sys
import os
import csv

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.db.session import SessionLocal, engine
from src.db.models import Base, RegionalWord

# Создаем таблицу, если ее еще нет
Base.metadata.create_all(bind=engine)

def load_csv_to_db(db, filepath):
    if not os.path.exists(filepath):
        print(f"⚠️ Файл не найден: {filepath}")
        return 0
    
    count = 0
    with open(filepath, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Мапим колонки из нашего CSV в поля модели RegionalWord
            lemma_val = row.get('word', '').strip()
            region_val = row.get('country', '').strip()
            standard_de_val = row.get('meaning', '').strip()
            
            if not lemma_val or not region_val:
                continue
            
            # Проверяем, есть ли уже такое слово в БД, чтобы избежать дубликатов
            exists = db.query(RegionalWord).filter_by(lemma=lemma_val, region=region_val).first()
            
            if not exists:
                db_word = RegionalWord(
                    lemma=lemma_val,
                    region=region_val,
                    standard_de=standard_de_val
                )
                db.add(db_word)
                count += 1
    return count

def seed_data():
    db = SessionLocal()
    
    # Определяем пути к нашим CSV файлам
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
    austria_path = os.path.join(base_dir, 'data', 'dictionaries', 'austriacisms.csv')
    swiss_path = os.path.join(base_dir, 'data', 'dictionaries', 'helvetisms.csv')
    
    print("📥 Загрузка словарей из CSV...")
    
    added_at = load_csv_to_db(db, austria_path)
    added_ch = load_csv_to_db(db, swiss_path)
    
    # Если добавились новые слова, сохраняем изменения
    if added_at > 0 or added_ch > 0:
        db.commit()
        print(f"✅ Успешно добавлено новых слов: {added_at} (AT), {added_ch} (CH)!")
    else:
        print("ℹ️ База актуальна. Новых слов в CSV не найдено.")
        
    db.close()

if __name__ == "__main__":
    seed_data()