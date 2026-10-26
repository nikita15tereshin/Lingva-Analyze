"""Пресеты матрицы параметров из ТЗ (пункт 4.4) и справочников P8.

seed_defaults() идемпотентен: существующие строки (по code/concept) не трогает,
маркеры можно править руками в таблице query_parameters без пересоздания.
"""

import json

from sqlalchemy.orm import Session

from src.db.models import LexicalPair, QueryParameter

DEFAULT_PARAMETERS = [
    {
        "code": "P1",
        "name": "Нормативность (долженствование)",
        "query_type": "LEMMA_SET",
        "markers": ["müssen", "sollen", "erforderlich", "notwendig"],
        "comment": "Поиск по леммам: musste/gemusst находятся как müssen (учет морфологии).",
    },
    {
        "code": "P2",
        "name": "Пассив и служебные конструкции",
        "query_type": "LEMMA_AND",
        "markers": [{"lemma": "werden", "pos": "AUX"}, {"lemma": "vorsehen"}],
        "comment": "Два слова в одном предложении (wird ... vorgesehen). Тип LEMMA_AND.",
    },
    {
        "code": "P3",
        "name": "Модальность",
        "query_type": "LEMMA_SET",
        "markers": ["wahrscheinlich", "vielleicht", "wohl", "man"],
        "comment": "Для сужения 'wohl + man в одном предложении' скопируйте параметр и смените тип на LEMMA_AND.",
    },
    {
        "code": "P4",
        "name": "Интертекстуальность (ссылки на НПА)",
        "query_type": "TEXT_REGEX",
        "markers": [r"§\s*\d+", r"Art\.\s*\d+"],
        "comment": "Параграфы и статьи кодексов по тексту предложения.",
    },
    {
        "code": "P5-P6",
        "name": "Австрицизмы и гельветизмы",
        "query_type": "DICTIONARY",
        "markers": [],
        "comment": "Прогон вхождений по regional_dictionary (см. seed_dictionary.py).",
    },
    {
        "code": "P8",
        "name": "Лексические замены",
        "query_type": "LEXICAL_PAIR",
        "markers": [],
        "comment": "Члены пар из справочника lexical_pairs (Bundeswehr/Bundesheer/Schweizer Armee).",
    },
    {
        "code": "P9",
        "name": "Гендерные формы (-in)",
        "query_type": "WORD_REGEX",
        "markers": [r"in\b"],
        "comment": "Регулярка по словоформе; при индекции сохраняется фактическая форма (Polizistin).",
    },
    {
        "code": "P7",
        "name": "Семантические сдвиги (гибрид: правила + LLM)",
        "query_type": "SEMANTIC_SHIFT",
        "markers": [],
        "comment": ("Омонимы из справочника semantic_shifts. Уверенные случаи "
                    "разметляет код по колокациям, спорные помечаются llm_pending "
                    "и добираются LLM одним пакетом."),
    },
    {
        "code": "STAT-YEARS",
        "name": "Цифры и годы в тексте",
        "query_type": "TEXT_REGEX",
        "markers": [r"\b(1[89]\d{2}|20\d{2})\b"],
        "comment": "Прикол Б: годы как отдельный маркер статистики.",
    },
    {
        "code": "FREQ-1-5",
        "name": "Слова с частотой от 1 до 5 в документе",
        "query_type": "FREQUENCY_RANGE",
        "markers": {"min": 1, "max": 5},
        "comment": "Прикол А: редкие леммы (не более 5 вхождений на документ).",
    },
]

DEFAULT_LEXICAL_PAIRS = [
    # concept, de_word, at_word, ch_word
    ("Вооруженные силы", "Bundeswehr", "Bundesheer", "Schweizer Armee"),
    ("Министерство внутренних дел", "Bundesministerium des Innern", "Bundesministerium für Inneres", "Eidgenössisches Departement für Umwelt, Verkehr, Energie und Kommunikation"),
    ("Ведомство безопасности", "Verfassungsschutz", "Verfassungsschutz", "fedpol"),
    ("Железная дорога", "Bahn", "ÖBB", "SBB"),
    ("Пиво низовой бродящий", "Pils", "Bier", "Bier"),
]

# Стартовый набор омонимов для P7 (пункт 3.2 ТЗ).
# word, country, meaning, collocations, examples (эталонные предложения для
# векторной линии; без них слово разбирается только правилами и LLM)
DEFAULT_SEMANTIC_SHIFTS = [
    ("Gymnasium", "DE", "тип средней школы с углубленной программой",
     ["schule", "abitur", "klassen", "lehrer", "maturanten", "unterricht"],
     ["Das Gymnasium ist eine Schule mit gymnasialer Bildung und Abitur.",
      "Die Lehrerin unterrichtet am Gymnasium drei Klassen."]),
    ("Gymnasium", "AT", "спортивный зал",
     ["sport", "geräte", "fitness", "turnsaal", "training"],
     ["Im Gymnasium der Universität stehen neue Geräte für das Training.",
      "Das Gymnasium ist mit Fitnessgeräten und Matten ausgestattet."]),
    ("Gymnasium", "CH", "тип средней школы (гимназия)",
     ["schule", "matura", "klassen", "lehrer", "unterricht"],
     ["Er besucht das Gymnasium und macht die Matura.",
      "Am Gymnasium unterrichten Lehrer verschiedene Schulfächer."]),
    ("Parlament", "DE", "бундестаг как институт; здание",
     ["bundestag", "abgeordnete", "gesetzgebung"],
     ["Das Parlament beschloss das Gesetz mit den Stimmen der Abgeordneten.",
      "Der Bundestag tagt im Parlament in Berlin."]),
    ("Parlament", "CH", "здание парламента (парламентское здание)",
     ["gebäude", "haus", "besucherdienst"],
     ["Das Parlamentsgebäude wurde nach einer Renovierung wieder eröffnet.",
      "Im Bundeshaus tagt das Parlament; der Besucherdienst führt Gruppen durch das Gebäude."]),
    ("Beamter", "DE", "лицо публично-правовой службы (статус)",
     ["verbeamtet", "besoldung", "statusrechtlich"],
     ["Der Beamte ist statusrechtlich angestellt und erhält Besoldung.",
      "Nach der Verbeamtung wechselte er in das Beamtenverhältnis."]),
    ("Beamter", "CH", "сотрудник государственной администрации в широком смысле",
     ["personal", "verwaltung", "angestellte"],
     ["Die Verwaltung beschäftigte mehrere Beamte im Personalwesen.",
      "Als Angestellter der Kantonsverwaltung gilt er als Beamter."]),
]


def seed_defaults(db: Session) -> dict:
    """Создает отсутствующие параметры, пары и омонимы. Возвращает счетчики."""
    from src.db.models import SemanticShift

    added_params = 0
    for spec in DEFAULT_PARAMETERS:
        exists = db.query(QueryParameter).filter(QueryParameter.code == spec["code"]).first()
        if exists:
            continue
        db.add(QueryParameter(
            code=spec["code"],
            name=spec["name"],
            query_type=spec["query_type"],
            markers=json.dumps(spec["markers"], ensure_ascii=False),
            comment=spec.get("comment"),
        ))
        added_params += 1

    added_pairs = 0
    for concept, de_w, at_w, ch_w in DEFAULT_LEXICAL_PAIRS:
        exists = db.query(LexicalPair).filter(LexicalPair.concept == concept).first()
        if exists:
            continue
        db.add(LexicalPair(concept=concept, de_word=de_w, at_word=at_w, ch_word=ch_w))
        added_pairs += 1

    added_shifts = 0
    for row in DEFAULT_SEMANTIC_SHIFTS:
        word, country, meaning, collocations = row[:4]
        examples = row[4] if len(row) > 4 else []
        exists = db.query(SemanticShift).filter(
            SemanticShift.word == word, SemanticShift.country == country,
            SemanticShift.meaning == meaning).first()
        if exists:
            continue
        db.add(SemanticShift(
            word=word, country=country, meaning=meaning,
            collocations=json.dumps(collocations, ensure_ascii=False),
            examples=json.dumps(examples, ensure_ascii=False),
        ))
        added_shifts += 1

    db.commit()
    return {"parameters": added_params, "lexical_pairs": added_pairs,
            "semantic_shifts": added_shifts}
