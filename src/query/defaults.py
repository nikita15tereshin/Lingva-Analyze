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
        "code": "STAT-YEARS",
        "name": "Цифры и годы в тексте",
        "query_type": "TEXT_REGEX",
        "markers": [r"\b(1[89]\d{2}|20\d{2})\b"],
        "comment": "Прикол Б: годы как отдельный маркер статистики.",
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


def seed_defaults(db: Session) -> dict:
    """Создает отсутствующие параметры и пары. Возвращает счетчики добавленного."""
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

    db.commit()
    return {"parameters": added_params, "lexical_pairs": added_pairs}
