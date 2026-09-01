import spacy

# Загружаем легковесную немецкую модель
try:
    nlp = spacy.load("de_core_news_sm")
except OSError:
    print("❌ Модель не найдена! Выполните: python -m spacy download de_core_news_sm")
    nlp = None

def process_text(text: str) -> dict:
    """
    Принимает строку текста и возвращает структуру:
    {"sentences": [{"sent_id": 0, "tokens": [{"word": str, "lemma": str, "pos": str}]}]}
    """
    if not nlp:
        raise RuntimeError("Модель spaCy не загружена.")

    # spaCy анализирует весь текст за один проход
    doc = nlp(text)
    
    result = {"sentences": []}

    # doc.sents - это генератор предложений, на которые spaCy уже разбил текст
    for sent_id, sentence in enumerate(doc.sents):
        tokens_list = []
        
        for token in sentence:
            # Игнорируем пробелы и переносы строк, нам нужны только реальные слова и пунктуация
            if not token.is_space:
                tokens_list.append({
                    "word": token.text,
                    "lemma": token.lemma_,
                    "pos": token.pos_
                })
        
        result["sentences"].append({
            "sent_id": sent_id,
            "tokens": tokens_list
        })

    return result

if __name__ == "__main__":
    # Небольшой тест для проверки работоспособности
    sample_text = "Hallo! Wie geht es dir heute? Das ist ein großartiger Test."
    
    if nlp:
        output = process_text(sample_text)
        
        # Выведем результат в красивом JSON-формате
        import json
        print(json.dumps(output, ensure_ascii=False, indent=2))