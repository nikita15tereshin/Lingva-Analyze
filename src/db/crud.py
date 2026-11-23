from sqlalchemy.orm import Session

from src.db.models import Document, Sentence, Token, LexicalIndex


def create_document(
    db: Session,
    filename: str,
    language: str = "de",
    external_code: str | None = None,
    country: str | None = None,
    doc_type: str | None = None,
    title: str | None = None,
    year: int | None = None,
) -> Document:
    """Создает запись о новом документе в БД (код DE-01/AT-02 и страна — опционально)."""
    db_doc = Document(
        filename=filename,
        language=language,
        external_code=external_code,
        country=country,
        doc_type=doc_type,
        title=title,
        year=year,
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)
    return db_doc


def save_nlp_data_to_db(db: Session, doc_id: int, nlp_data: dict):
    """
    Сохраняет предложения и лексический индекс пакетно (для больших документов).

    Позиция считается по реальным словам (PUNCT/SPACE не индексируются), заодно
    фиксируется точная словоформа (word_form) — без нее невозможен поиск
    по суффиксам (P9) и подсветка найденного слова в предложении.
    """
    sentences_data = nlp_data.get("sentences", [])
    if not sentences_data:
        return

    # 1. Собираем уникальные (lemma, pos) и пакетно синхронизируем таблицу tokens
    needed_keys: set[tuple[str, str]] = set()
    for sent_data in sentences_data:
        for token_data in sent_data["tokens"]:
            if token_data["pos"] not in ("PUNCT", "SPACE"):
                needed_keys.add((token_data["lemma"], token_data["pos"]))

    token_cache: dict[tuple[str, str], int] = {}
    unique_lemmas = list({lemma for lemma, _ in needed_keys})
    for i in range(0, len(unique_lemmas), 500):
        batch = unique_lemmas[i:i + 500]
        for tok in db.query(Token).filter(Token.lemma.in_(batch)).all():
            token_cache[(tok.lemma, tok.pos)] = tok.id

    missing_tokens = [
        Token(lemma=lemma, pos=pos)
        for lemma, pos in sorted(needed_keys)
        if (lemma, pos) not in token_cache
    ]
    if missing_tokens:
        db.add_all(missing_tokens)
        db.flush()
        for tok in missing_tokens:
            token_cache[(tok.lemma, tok.pos)] = tok.id

    # 2. Пакетно вставляем предложения одним flush
    db_sentences = [
        Sentence(
            document_id=doc_id,
            sentence_number=sent_data["sent_id"],
            text=" ".join(t["word"] for t in sent_data["tokens"]),
        )
        for sent_data in sentences_data
    ]
    db.add_all(db_sentences)
    db.flush()

    # 3. Пакетно вставляем лексический индекс
    index_mappings: list[dict] = []
    for db_sent, sent_data in zip(db_sentences, sentences_data):
        word_position = 0
        for token_data in sent_data["tokens"]:
            pos_tag = token_data["pos"]
            if pos_tag in ("PUNCT", "SPACE"):
                continue
            index_mappings.append({
                "token_id": token_cache[(token_data["lemma"], pos_tag)],
                "sentence_id": db_sent.id,
                "position": word_position,
                "word_form": token_data["word"],
            })
            word_position += 1

    for i in range(0, len(index_mappings), 5000):
        db.bulk_insert_mappings(LexicalIndex, index_mappings[i:i + 5000])

    db.commit()

def get_document_index_from_db(db: Session, doc_id: int) -> dict:
    """
    Восстанавливает лексический индекс документа из БД.
    Формат: {lemma: [(sent_num, position), ...]}
    """
    index_dict = {}

    occurrences = (
        db.query(LexicalIndex.position, Token.lemma, Sentence.sentence_number)
        .join(Token, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(Sentence.document_id == doc_id)
        .all()
    )

    for position, lemma, sent_num in occurrences:
        index_dict.setdefault(lemma, []).append((sent_num, position))

    return index_dict


def get_frequency_table(db: Session, doc_id: int) -> list[dict]:
    """Частотный словарь лемм документа (количественный показатель, пункт 4.1)."""
    rows = (
        db.query(Token.lemma, Token.pos, LexicalIndex.position)
        .join(LexicalIndex, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(Sentence.document_id == doc_id)
        .all()
    )

    counts: dict[tuple[str, str], int] = {}
    for lemma, pos, _ in rows:
        counts[(lemma, pos)] = counts.get((lemma, pos), 0) + 1

    return [
        {"lemma": lemma, "pos": pos, "count": count}
        for (lemma, pos), count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
