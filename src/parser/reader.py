import os
import re
import io

import docx
import fitz  # PyMuPDF — заметно лучше PyPDF2 справляется с реальными госотчетами


def normalize_text(text: str) -> str:
    """
    Удаление лишних пробелов и спецсимволов.
    ВАЖНО: для немецкого НЕ приводим к нижнему регистру — spaCy опирается
    на заглавные буквы при распознавании существительных.
    """
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def read_txt(file_obj) -> str:
    """Извлечение текста из TXT (поддерживает путь или объект в памяти)."""
    if isinstance(file_obj, str):
        with open(file_obj, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return file_obj.read().decode('utf-8')


def _table_to_lines(table) -> list[str]:
    """Таблицу PDF превращаем в строки 'заголовок: значение' — иначе нумерация
    колонок теряет смысл после склейки текста страницы."""
    lines = []
    header = [c.text.strip() for c in table[0]] if len(table) > 1 else []
    for row in table[1:] if len(table) > 1 else table:
        cells = [c.text.strip() for c in row]
        if not any(cells):
            continue
        if header and len(header) == len(cells):
            pairs = [f"{h} {v}".strip() for h, v in zip(header, cells) if v]
            lines.append("; ".join(pairs))
        else:
            lines.append(" ".join(c for c in cells if c))
    return lines


def read_pdf(file_obj) -> str:
    """Извлечение текста из PDF через PyMuPDF, таблицы — отдельно построчно."""
    if isinstance(file_obj, str):
        with open(file_obj, "rb") as f:
            file_obj = io.BytesIO(f.read())

    doc = fitz.open(stream=file_obj.read(), filetype="pdf")
    parts = []
    for page in doc:
        parts.append(page.get_text("text"))
        try:
            for tbl in page.find_tables().tables:
                parts.extend(_table_to_lines(tbl))
        except Exception:
            pass  # если разбор таблиц не удался, ограничиваемся обычным текстом
    doc.close()
    return "\n".join(parts)


def read_docx(file_obj) -> str:
    """Извлечение текста из DOCX: абзацы плюс таблицы (строки через ';')."""
    if isinstance(file_obj, str):
        with open(file_obj, "rb") as f:
            file_obj = io.BytesIO(f.read())

    doc = docx.Document(file_obj)
    text = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                text.append("; ".join(cells))
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
    print("Модуль парсера готов к работе! Поддерживает: TXT, PDF (PyMuPDF + таблицы), DOCX.")
