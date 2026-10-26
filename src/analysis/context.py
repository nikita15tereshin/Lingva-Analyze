from sqlalchemy.orm import Session

from src.db.models import Token, LexicalIndex, Sentence


def get_contexts_for_lemma(db: Session, lemma: str, document_id: int) -> list[dict]:
    """
    Все вхождения леммы в документе с контекстом (предложение + соседи).
    Один запрос на вхождения и один на все нужные предложения — без N+1.
    """
    occurrences = (
        db.query(LexicalIndex, Sentence.sentence_number)
        .join(Token, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(
            Token.lemma == lemma,
            Sentence.document_id == document_id,
        )
        .all()
    )

    if not occurrences:
        return []

    needed_numbers = set()
    for occ, sent_num in occurrences:
        needed_numbers.update({sent_num - 1, sent_num, sent_num + 1})

    sentences_by_number = {
        s.sentence_number: s
        for s in db.query(Sentence).filter(
            Sentence.document_id == document_id,
            Sentence.sentence_number.in_(needed_numbers),
        ).all()
    }

    contexts = []
    for occ, sent_num in occurrences:
        surrounding = [
            sentences_by_number[n]
            for n in sorted(needed_numbers)
            if n in sentences_by_number and abs(n - sent_num) <= 1
        ]
        full_context_text = " ".join(s.text for s in surrounding)

        contexts.append({
            "lemma": lemma,
            "document_id": document_id,
            "target_sentence": sentences_by_number[sent_num].text,
            "full_context": full_context_text,
            "position": occ.position,
            "word_form": occ.word_form,
        })

    return contexts
