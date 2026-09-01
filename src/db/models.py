from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Document(Base):
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    language = Column(String, default="de")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    sentences = relationship("Sentence", back_populates="document", cascade="all, delete-orphan")

class Sentence(Base):
    __tablename__ = 'sentences'
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete="CASCADE"))
    sentence_number = Column(Integer)
    text = Column(Text, nullable=False)
    
    document = relationship("Document", back_populates="sentences")
    occurrences = relationship("LexicalIndex", back_populates="sentence", cascade="all, delete-orphan")

class Token(Base):
    __tablename__ = 'tokens'
    
    id = Column(Integer, primary_key=True, index=True)
    lemma = Column(String, unique=True, index=True, nullable=False)
    
    occurrences = relationship("LexicalIndex", back_populates="token")

class LexicalIndex(Base):
    __tablename__ = 'lexical_index'
    
    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(Integer, ForeignKey('tokens.id', ondelete="CASCADE"))
    sentence_id = Column(Integer, ForeignKey('sentences.id', ondelete="CASCADE"))
    position = Column(Integer)
    frequency = Column(Integer, default=1)
    
    token = relationship("Token", back_populates="occurrences")
    sentence = relationship("Sentence", back_populates="occurrences")

class ComparisonResult(Base):
    __tablename__ = 'comparison_results'
    
    id = Column(Integer, primary_key=True, index=True)
    lemma_a = Column(String, nullable=False)
    lemma_b = Column(String, nullable=False)
    confidence = Column(Float)
    llm_comment = Column(Text)

class RegionalWord(Base):
    # Тут моделька для австрицизмов и гельветизмов
    __tablename__ = "regional_dictionary"

    id = Column(Integer, primary_key=True, index=True)
    lemma = Column(String, index=True, nullable=False)
    region = Column(String, index=True, nullable=False)
    standard_de = Column(String, nullable=True)