from sqlalchemy.orm import Session
from src.db.models import RegionalWord

def classify_unique_words(db: Session, unique_words: list) -> dict:
    """
    Принимает список лемм и сверяет их со словарем в БД.
    Возвращает словарь с разбиением по регионам и стандартам.
    """
    result = {
        "AT_matches": [],  # Найденные австрицизмы (с метаданными)
        "CH_matches": [],  # Найденные гельветизмы (с метаданными)
        "unknown": []      # Обычный шум или новые слова
    }
    
    if not unique_words:
        return result
        
    # Делаем быстрый запрос в БД: ищем все слова из нашего списка
    found_words = db.query(RegionalWord).filter(RegionalWord.lemma.in_(unique_words)).all()
    
    # ИЗМЕНЕНИЕ 1: Сохраняем в справочник не только регион, но и объект целиком (или нужные поля)
    db_map = {w.lemma: {"region": w.region, "standard_de": w.standard_de} for w in found_words}
    
    # Распределяем слова по корзинам
    for word in unique_words:
        word_info = db_map.get(word)
        
        if word_info:
            # ИЗМЕНЕНИЕ 2: Формируем структуру с данными для LLM и UI
            match_data = {
                "lemma": word,
                "standard_de": word_info["standard_de"]
            }
            
            if word_info["region"] == "AT":
                result["AT_matches"].append(match_data)
            elif word_info["region"] == "CH":
                result["CH_matches"].append(match_data)
        else:
            # Неизвестные слова можно оставлять просто строками
            result["unknown"].append(word)
            
    return result