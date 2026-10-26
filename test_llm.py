import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.analysis.llm import analyze_semantic_context_stream


def main():
    word = "Gymnasium"
    sentence = "Wir treffen uns heute Abend im Gymnasium, um Basketball zu spielen."
    region = "CH"

    print(f"Отправляем слово: {word}")
    print(f"Контекст: {sentence}\n")

    chunks = []
    for chunk in analyze_semantic_context_stream(word, sentence, region):
        print(chunk, end="", flush=True)
        chunks.append(chunk)

    print("\n--- Конец ответа ---")
    if not chunks:
        print("LLM не вернула ответ. Проверьте переменную окружения LLM_API_KEY.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
