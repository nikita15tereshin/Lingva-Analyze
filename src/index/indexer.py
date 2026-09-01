import json
import os

def build_index(doc_id: int, sentences: list) -> dict:
    """
    Создает лексический индекс из списка предложений.
    Возвращает словарь формата: {lemma: [(sent_id, position), ...]}
    """
    index = {}
    
    for sentence in sentences:
        sent_id = sentence.get("sent_id")
        tokens = sentence.get("tokens", [])
        
        for position, token in enumerate(tokens):
            lemma = token.get("lemma")
            pos = token.get("pos")
            
            # Игнорируем знаки препинания и пробелы, нам нужны только реальные слова
            if pos in ["PUNCT", "SPACE"]:
                continue
                
            if lemma not in index:
                index[lemma] = []
                
            # Добавляем координаты слова (номер предложения, позиция в предложении)
            index[lemma].append((sent_id, position))
            
    return index

def save_index_to_json(index: dict, filepath: str) -> None:
    """Сохраняет построенный индекс в JSON-файл."""
    # Создаем папку, если ее вдруг нет
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        # ensure_ascii=False нужен, чтобы немецкие умлауты (ä, ö, ü) сохранялись нормально
        json.dump(index, f, ensure_ascii=False, indent=2)

def load_index_from_json(filepath: str) -> dict:
    """Загружает индекс из JSON-файла."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Файл индекса не найден: {filepath}")
        
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

if __name__ == "__main__":
    # Тест на маленьком тексте (2 предложения), как указано в MVP
    test_sentences = [
        {
            "sent_id": 0,
            "tokens": [
                {"word": "Das", "lemma": "der", "pos": "PRON"},
                {"word": "ist", "lemma": "sein", "pos": "AUX"},
                {"word": "ein", "lemma": "ein", "pos": "DET"},
                {"word": "Test", "lemma": "Test", "pos": "NOUN"},
                {"word": ".", "lemma": ".", "pos": "PUNCT"}
            ]
        },
        {
            "sent_id": 1,
            "tokens": [
                {"word": "Ein", "lemma": "ein", "pos": "DET"},
                {"word": "guter", "lemma": "gut", "pos": "ADJ"},
                {"word": "Test", "lemma": "Test", "pos": "NOUN"},
                {"word": ".", "lemma": ".", "pos": "PUNCT"}
            ]
        }
    ]
    
    print("1️⃣ Строим индекс...")
    my_index = build_index(doc_id=1, sentences=test_sentences)
    print(my_index)
    
    test_file = "data/test_index.json"
    print(f"\n2️⃣ Сохраняем индекс в файл {test_file}...")
    save_index_to_json(my_index, test_file)
    
    print("\n3️⃣ Загружаем индекс обратно из файла...")
    loaded_index = load_index_from_json(test_file)
    print(loaded_index)
    
    print("\n✅ Блок 4 успешно завершен!")