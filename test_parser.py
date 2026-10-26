import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.parser.reader import extract_and_normalize


def main():
    pdf_filename = "test.pdf"
    pdf_path = os.path.join("data", pdf_filename)

    if not os.path.exists(pdf_path):
        print(f"Файл не найден: {pdf_path}")
        print("Положите PDF-файл в папку data/ и укажите его имя в переменной pdf_filename.")
        return 1

    print(f"Открываю файл: {pdf_path}...")
    text = extract_and_normalize(pdf_path, pdf_filename)

    print(f"Успех! Извлечено символов: {len(text)}")
    print("--- Первые 500 символов текста ---")
    print(text[:500])
    print("---------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
