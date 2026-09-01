def find_unique_lemmas(index_A: dict, index_B: dict) -> dict:
    """
    Сравнивает два лексических индекса и находит уникальные леммы.
    Возвращает словарь с двумя списками уникальных слов.
    """
    # Превращаем ключи (леммы) словарей в множества (set) для быстрого сравнения
    lemmas_a = set(index_A.keys())
    lemmas_b = set(index_B.keys())
    
    # Находим разницу множеств
    unique_a = lemmas_a - lemmas_b
    unique_b = lemmas_b - lemmas_a
    
    # Возвращаем отсортированные списки для красоты
    return {
        "unique_A": sorted(list(unique_a)),
        "unique_B": sorted(list(unique_b))
    }

def print_comparison_table(result: dict, name_a: str = "Документ A", name_b: str = "Документ B") -> None:
    """
    Выводит результат сравнения в виде аккуратной текстовой таблицы.
    """
    list_a = result.get("unique_A", [])
    list_b = result.get("unique_B", [])
    
    # Определяем, сколько строк будет в таблице (по самому длинному списку)
    max_rows = max(len(list_a), len(list_b))
    
    print(f"\n| {name_a:<25} | {name_b:<25} |")
    print("-" * 57)
    
    if max_rows == 0:
        print(f"| {'Нет уникальных слов':<25} | {'Нет уникальных слов':<25} |")
        return

    for i in range(max_rows):
        word_a = list_a[i] if i < len(list_a) else ""
        word_b = list_b[i] if i < len(list_b) else ""
        print(f"| {word_a:<25} | {word_b:<25} |")
    print("-" * 57)

if __name__ == "__main__":
    # Тестовые индексы (имитируем результат работы нашего Блока 4)
    index_doc_1 = {
        "der": [(0, 0)],
        "sein": [(0, 1)],
        "ein": [(0, 2)],
        "Apfel": [(0, 3)]
    }
    
    index_doc_2 = {
        "der": [(0, 0)],
        "sein": [(0, 1)],
        "ein": [(0, 2)],
        "Banane": [(0, 3)],
        "gut": [(0, 4)]
    }
    
    print("Запускаем движок сравнения...")
    results = find_unique_lemmas(index_doc_1, index_doc_2)
    
    print_comparison_table(results, "Текст про яблоко", "Текст про банан")