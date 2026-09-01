from sqlalchemy.orm import Session
from src.db.models import Document, Sentence, Token, LexicalIndex

def create_document(db: Session, filename: str, language: str = "de") -> Document:
    """Создает запись о новом документе в БД."""
    db_doc = Document(filename=filename, language=language)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)
    return db_doc

def save_nlp_data_to_db(db: Session, doc_id: int, nlp_data: dict):
    """
    Сохраняет предложения и лексический индекс в строгом соответствии с моделями БД.
    """
    for sent_data in nlp_data.get("sentences", []):
        # 1. Сохраняем предложение
        db_sent = Sentence(
            document_id=doc_id, 
            sentence_number=sent_data["sent_id"],
            text=" ".join([t["word"] for t in sent_data["tokens"]])
        )
        db.add(db_sent)
        db.flush() # Получаем db_sent.id без полного коммита

        # 2. Обрабатываем токены
        for pos, token_data in enumerate(sent_data["tokens"]):
            lemma_str = token_data["lemma"]
            pos_tag = token_data["pos"]
            
            # Игнорируем пунктуацию и пробелы
            if pos_tag in ["PUNCT", "SPACE"]:
                continue
                
            # Проверяем, есть ли уже такая лемма в базе Token
            db_token = db.query(Token).filter(Token.lemma == lemma_str).first()
            if not db_token:
                db_token = Token(lemma=lemma_str)
                db.add(db_token)
                db.flush() # Получаем db_token.id
                
            # 3. Сохраняем координату (Лексический индекс)
            db_index = LexicalIndex(
                token_id=db_token.id,
                sentence_id=db_sent.id,
                position=pos
            )
            db.add(db_index)
            
    # Записываем всё в базу одним пакетом
    db.commit()

def get_document_index_from_db(db: Session, doc_id: int) -> dict:
    """
    Восстанавливает словарь индексов из базы данных для нужд сравнения.
    Формат: {lemma: [(sent_id, position), ...]}
    """
    index_dict = {}
    
    # Достаем все индексы для конкретного документа через JOIN
    occurrences = (
        db.query(LexicalIndex, Token.lemma, Sentence.sentence_number)
        .join(Token, LexicalIndex.token_id == Token.id)
        .join(Sentence, LexicalIndex.sentence_id == Sentence.id)
        .filter(Sentence.document_id == doc_id)
        .all()
    )
    
    for occ, lemma, sent_num in occurrences:
        if lemma not in index_dict:
            index_dict[lemma] = []
        index_dict[lemma].append((sent_num, occ.position))
        
    return index_dict