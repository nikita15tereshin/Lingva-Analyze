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
    Сохраняет предложения и лексический индекс.

    Позиция считается по реальным словам (PUNCT не индексируется), заодно
    фиксируется точная словоформа (word_form) — без нее невозможен поиск
    по суффиксам (P9) и подсветка найденного слова в предложении.
    """
    token_cache: dict[tuple[str, str], int] = {}

    for sent_data in nlp_data.get("sentences", []):
        words = [t["word"] for t in sent_data["tokens"]]
        db_sent = Sentence(
            document_id=doc_id,
            sentence_number=sent_data["sent_id"],
            text=" ".join(words),
        )
        db.add(db_sent)
        db.flush()

        word_position = 0
        for token_data in sent_data["tokens"]:
            lemma_str = token_data["lemma"]
            pos_tag = token_data["pos"]

            if pos_tag in ("PUNCT", "SPACE"):
                continue

            key = (lemma_str, pos_tag)
            token_id = token_cache.get(key)
            if token_id is None:
                db_token = (
                    db.query(Token)
                    .filter(Token.lemma == lemma_str, Token.pos == pos_tag)
                    .first()
                )
                if not db_token:
                    db_token = Token(lemma=lemma_str, pos=pos_tag)
                    db.add(db_token)
                    db.flush()
                token_id = db_token.id
                token_cache[key] = token_id

            db.add(LexicalIndex(
                token_id=token_id,
                sentence_id=db_sent.id,
                position=word_position,
                word_form=token_data["word"],
            ))
            word_position += 1

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
