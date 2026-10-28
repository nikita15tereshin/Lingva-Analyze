"""Общие типы и хелперы стратегий извлечения словарей.

Стратегия (паттерн Strategy): каждая реализация отвечает за свой тип
источника (PDF, простой HTML, JS-сайт) и регистрируется в registry.py по
значению поля SourceSpec.extraction. Точка входа для всех — extract(spec).
"""

import re
from dataclasses import dataclass, field


@dataclass
class DictEntry:
    term: str
    definition: str
    region: str                      # DE / AT / CH
    source_key: str
    meta: dict = field(default_factory=dict)

    def normalized(self) -> "DictEntry":
        term = normalize_term(self.term)
        return DictEntry(term, self.definition.strip(), self.region,
                         self.source_key, self.meta)


def normalize_term(term: str) -> str:
    """Приводит термин к словарному виду: без артикля, точек, кавычек."""
    t = re.sub(r"\s+", " ", term).strip(" .,:;\u00a0")
    t = re.sub(r"^(der|die|das)\s+", "", t, flags=re.I)
    t = t.replace("\u201e", '"').replace("\u201c", '"')
    return t


def clean_definition(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    # хвостовые элементы страниц: "Quelle:", кнопки, якоря
    t = re.sub(r"(Quelle|Quellenangabe):\s*\S*.*$", "", t).strip(" -:\u00a0")
    return t


def make_entry(term: str, definition: str, region: str,
               source_key: str, meta: dict | None = None) -> DictEntry:
    return DictEntry(normalize_term(term), clean_definition(definition),
                     region, source_key, meta or {})


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de-CH;q=0.9,de;q=0.8",
}

# Таймаут навигации браузера, мс: зависший сайт не должен вешать синхронизацию.
NAV_TIMEOUT_MS = 30000


class FetchError(RuntimeError):
    """Стратегия не смогла получить данные источника."""


class SourceStrategy:
    """Базовая стратегия извлечения пар термин-определение."""

    name: str = "base"

    def extract(self, spec) -> list[DictEntry]:
        raise NotImplementedError
