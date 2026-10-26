import os

import spacy

MODEL_NAME = os.getenv("SPACY_MODEL", "de_core_news_sm")

# Загружаем немецкую модель; для госотчетов можно переключиться на de_core_news_lg
try:
    nlp = spacy.load(MODEL_NAME)
except OSError:
    print(f"Модель spaCy не найдена! Выполните: python -m spacy download {MODEL_NAME}")
    nlp = None


def process_text(text: str) -> dict:
    """
    Принимает строку текста и возвращает структуру:
    {"sentences": [{"sent_id": 0, "tokens": [{"word": str, "lemma": str, "pos": str}]}]}
    """
    if not nlp:
        raise RuntimeError("Модель spaCy не загружена.")

    doc = nlp(text)

    result = {"sentences": []}

    for sent_id, sentence in enumerate(doc.sents):
        tokens_list = []

        for token in sentence:
            # Пробелы отбрасываем, пунктуацию сохраняем — по ней идут границы предложений
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
