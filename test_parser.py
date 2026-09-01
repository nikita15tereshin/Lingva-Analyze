from src.parser.reader import PDFReader
import os

# Укажи путь к твоему файлу в папке data/
pdf_filename = "test.pdf"  # <-- СЮДА ВПИШИ ИМЯ СВОЕГО ФАЙЛА
pdf_path = os.path.join("data", pdf_filename)

try:
    print(f"📄 Открываю файл: {pdf_path}...")
    reader = PDFReader(pdf_path)
    text = reader.extract_text()
    
    print(f"✅ Успех! Извлечено символов: {len(text)}")
    print("--- Первые 500 символов текста ---")
    print(text[:500])
    print("---------------------------------")
    
except Exception as e:
    print(f"❌ Ошибка: {e}")