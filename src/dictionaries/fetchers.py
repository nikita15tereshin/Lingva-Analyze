"""Фасад извлечения пар "термин - определение" (обратная совместимость).

Архитектура перестроена на паттерн "Стратегия": конкретная логика живет в
модулях pdf.py, html_generic.py, termdat_legacy.py и подключается через
реестр registry.py по полю SourceSpec.extraction. Здесь остаются только
реэкспорт публичных имен и тонкая обертка extract_entries — весь внешний
код (sync.py, validator.py, тесты) продолжает импортировать fetchers без
изменений.

Конвейер не изменился: fetch -> parse -> validate -> staging в БД.
Playwright/camoufox подключаются лениво (browser.py): если пакет не
установлен, модуль работает только с HTTP-источниками и сообщает об этом
вызывающему коду через FetchError/ImportError.
"""

from src.dictionaries.base import (DEFAULT_HEADERS, DictEntry, FetchError,
                                   clean_definition, make_entry,
                                   normalize_term)
from src.dictionaries.browser import close_browser, headless_available
from src.dictionaries.browser import render as fetch_html_headless
from src.dictionaries.html_generic import (_region_from_row, parse_accordions,
                                           parse_cards, parse_dlists,
                                           parse_html, parse_tables)
from src.dictionaries.pdf import parse_pdf_lines
from src.dictionaries.registry import extract_entries, register, resolve
from src.dictionaries.termdat_legacy import (TERM_DAT_BASE, parse_termdat)

import requests

from src.dictionaries.pdf import _extract_text as _pdf_text


def fetch_html(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def fetch_pdf_bytes(url: str, timeout: int = 60) -> bytes:
    from src.dictionaries.pdf import PdfGlossaryStrategy
    return PdfGlossaryStrategy().download(url, timeout=timeout)


def parse_pdf_glossary(pdf_bytes: bytes, source_key: str,
                       region: str) -> list[DictEntry]:
    """Совместимость со старым API: байты PDF -> список пар."""
    return parse_pdf_lines(_pdf_text(pdf_bytes), region, source_key)


__all__ = [
    "DEFAULT_HEADERS", "DictEntry", "FetchError", "TERM_DAT_BASE",
    "clean_definition", "close_browser", "extract_entries", "fetch_html",
    "fetch_html_headless", "fetch_pdf_bytes", "headless_available",
    "make_entry", "normalize_term", "parse_accordions", "parse_cards",
    "parse_dlists", "parse_html", "parse_pdf_glossary", "parse_tables",
    "parse_termdat", "register", "resolve",
]
