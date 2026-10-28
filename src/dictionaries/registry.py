"""Реестр стратегий извлечения: extraction-тип источника -> реализация.

Раньше диспетчеризация была захардкожена в if/else внутри
fetchers.extract_entries, и новый тип источника требовал правки общего кода.
Теперь strategy-модуль (pdf.py, html_generic.py, ...) экспортирует объект
`strategy`, а здесь он регистрируется одной строкой. Порядок важен только
для дефолта; конкретные значения spec.extraction выигрывают у map-алиасов.
"""

from src.dictionaries.base import DictEntry, FetchError, SourceStrategy
from src.dictionaries.html_generic import strategy as html_strategy
from src.dictionaries.pdf import strategy as pdf_strategy

# соответствие поля SourceSpec.extraction -> стратегия
_BY_EXTRACTION: dict[str, SourceStrategy] = {
    "pdf_glossary": pdf_strategy,
    "html_table": html_strategy,
    "html_terms": html_strategy,
}

_FALLBACK = html_strategy


def resolve(spec) -> SourceStrategy:
    strategy = _BY_EXTRACTION.get(spec.extraction)
    if strategy is None:
        # termdat_api и будущие специфичные стратегии зарегистрируются здесь
        return _FALLBACK
    return strategy


def register(strategy: SourceStrategy, *extraction_keys: str):
    """Подключение новой стратегии без правок этого модуля извне."""
    for key in extraction_keys or (strategy.name,):
        _BY_EXTRACTION[key] = strategy


def extract_entries(spec, headless: bool | None = None) -> list[DictEntry]:
    """Точка входа: спецификация источника -> список пар слово-значение.

    Аргумент headless позволяет UI/API форсировать браузерный рендер;
    None — решение по флагу самого источника.
    """
    if spec.extraction == "termdat_api":
        from src.dictionaries.termdat_legacy import parse_termdat
        return parse_termdat(spec.key)
    strategy = resolve(spec)
    if headless is not None and hasattr(spec, "headless"):
        spec = _with_headless(spec, headless)
    return strategy.extract(spec)


def _with_headless(spec, headless: bool):
    import copy
    clone = copy.copy(spec)
    clone.headless = headless
    return clone


__all__ = ["DictEntry", "FetchError", "extract_entries", "register",
           "resolve"]
