import os
import re
import io
from PyPDF2 import PdfReader
import docx

def normalize_text(text: str) -> str:
    """
    Удаление лишних пробелов и спецсимволов.
    ВАЖНО: Для немецкого языка мы НЕ используем .lower(), 
    так как spaCy опирается на заглавные буквы для поиска существительных!
    """
    # Заменяем множественные пробелы и переносы строк на один пробел
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def read_txt(file_obj) -> str:
    """Извлечение текста из TXT (поддерживает путь или объект в памяти)."""
    if isinstance(file_obj, str):
        with open(file_obj, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return file_obj.read().decode('utf-8')

def read_pdf(file_obj) -> str:
    """Извлечение текста из PDF с помощью PyPDF2."""
    reader = PdfReader(file_obj)
    text = []
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text.append(extracted)
    return " ".join(text)

def read_docx(file_obj) -> str:
    """Извлечение текста из DOCX с помощью python-docx."""
    doc = docx.Document(file_obj)
    text = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
    return " ".join(text)

def extract_and_normalize(file_obj, filename: str, normalize: bool = True) -> str:
    """
    Главная функция: определяет формат файла по имени, 
    читает его из памяти или с диска и нормализует.
    """
    ext = os.path.splitext(filename)[1].lower()
    
    if ext == '.txt':
        raw_text = read_txt(file_obj)
    elif ext == '.pdf':
        raw_text = read_pdf(file_obj)
    elif ext == '.docx':
        raw_text = read_docx(file_obj)
    else:
        raise ValueError(f"Формат файла {ext} не поддерживается. Используйте TXT, PDF или DOCX.")
        
    if normalize:
        return normalize_text(raw_text)
        
    return raw_text

if __name__ == "__main__":
    print("Модуль парсера готов к работе! Поддерживает: TXT, PDF, DOCX (и потоки Streamlit).")