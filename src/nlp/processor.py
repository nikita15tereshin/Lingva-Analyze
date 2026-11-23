import os

import spacy

MODEL_NAME = os.getenv("SPACY_MODEL", "de_core_news_sm")
DEFAULT_CHUNK_SIZE = 80_000

# Загружаем немецкую модель; для госотчетов можно переключиться на de_core_news_lg
try:
    nlp = spacy.load(MODEL_NAME)
except OSError:
    print(f"Модель spaCy не найдена! Выполните: python -m spacy download {MODEL_NAME}")
    nlp = None


def _split_text_chunks(text: str, max_chars: int = DEFAULT_CHUNK_SIZE) -> list[str]:
    """Режет длинный текст на куски <= max_chars по границам предложений/пробелов."""
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    n = len(text)
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            split_at = -1
            for sep in (chr(10), ". ", "! ", "? "):
                pos = text.rfind(sep, start, end)
                if pos > start + max_chars // 2:
                    split_at = max(split_at, pos + len(sep))
            if split_at == -1:
                space_pos = text.rfind(" ", start, end)
                if space_pos > start:
                    split_at = space_pos + 1
            if split_at != -1:
                end = split_at

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def process_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    """
    Принимает строку текста и возвращает структуру:
    {"sentences": [{"sent_id": 0, "tokens": [{"word": str, "lemma": str, "pos": str}]}]}
    """
    if not nlp:
        raise RuntimeError("Модель spaCy не загружена.")

    chunks = _split_text_chunks(text, max_chars=chunk_size)
    result = {"sentences": []}
    sent_id = 0

    for doc in nlp.pipe(chunks):
        for sentence in doc.sents:
            tokens_list = [
                {
                    "word": token.text,
                    "lemma": token.lemma_,
                    "pos": token.pos_,
                }
                for token in sentence
                if not token.is_space
            ]
            if tokens_list:
                result["sentences"].append({
                    "sent_id": sent_id,
                    "tokens": tokens_list,
                })
                sent_id += 1

    return result
