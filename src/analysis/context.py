from sqlalchemy.orm import Session
from src.db.models import Token, LexicalIndex, Sentence

def get_contexts_for_lemma(db: Session, lemma: str, document_id: int) -> list[dict]:
    """
    Находит все вхождения леммы в документе и возвращает контекст 
    (само предложение + соседние предложения).
    """
    contexts = []
    
    # 1. Находим все вхождения этой леммы в конкретном документе через связи
    occurrences = (
        db.query(LexicalIndex)
        .join(Token, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(
            Token.lemma == lemma,
            Sentence.document_id == document_id
        )
        .all()
    )
    
    if not occurrences:
        return contexts
        
    # 2. Для каждого вхождения собираем контекст
    for occ in occurrences:
        target_sentence = occ.sentence
        sent_num = target_sentence.sentence_number
        
        # Достаем предыдущее, текущее и следующее предложения (окно контекста)
        surrounding = (
            db.query(Sentence)
            .filter(
                Sentence.document_id == document_id,
                Sentence.sentence_number.in_([sent_num - 1, sent_num, sent_num + 1])
            )
            .order_by(Sentence.sentence_number)
            .all()
        )
        
        # Склеиваем текст предложений в один абзац
        full_context_text = " ".join([s.text for s in surrounding])
        
        contexts.append({
            "lemma": lemma,
            "document_id": document_id,
            "target_sentence": target_sentence.text,
            "full_context": full_context_text,
            "position": occ.position
        })
        
    return contexts