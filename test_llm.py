import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.analysis.llm import analyze_semantic_context

print("🚀 Запуск тестового скрипта Kimi...")

def main():
    word = "Gymnasium"
    sentence = "Wir treffen uns heute Abend im Gymnasium, um Basketball zu spielen."
    region = "CH"
    
    print(f"🔍 Отправляем слово: {word}")
    print(f"📝 Контекст: {sentence}\n")
    
    # Вызываем нашу функцию
    result = analyze_semantic_context(word, sentence, region)
    
    print("\n🤖 --- Ответ LLM (Kimi) ---")
    print(result)
    print("----------------------------")

if __name__ == "__main__":
    main()