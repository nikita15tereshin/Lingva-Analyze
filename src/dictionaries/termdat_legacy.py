"""Стратегия для Terminology-Datenbank des Bundes (CH).

Почему не браузер: termdat.bk.admin.ch — SPA с поисковым интерфейсом,
но у швейцарской федеральной канцелярии есть публичный REST API
(termdat.admin.ch/rest/v1/concepts), который отдает те же данные в JSON.
API надежнее и быстрее рендера; переписывать его на Playwright смысла нет.

На следующий этап здесь же планируется отдельная стратегия-браузер для
алфавитной пагинации сложных сайтов (alphabetic.py) — эта функция пока
остается в виде прямой функции без класса, чтобы не менять поведение.
"""

import time

import requests

from src.dictionaries.base import DEFAULT_HEADERS, DictEntry, make_entry  # noqa: F401

TERM_DAT_BASE = "https://termdat.admin.ch/rest/v1/concepts"


def parse_termdat(source_key: str, per_page: int = 100,
                  max_items: int | None = None,
                  sleep_s: float = 0.4) -> list[DictEntry]:
    """Публичный JSON API Terminology-Datenbank des Bundes (de-CH)."""
    entries: list[DictEntry] = []
    skip = 0
    while True:
        r = requests.get(TERM_DAT_BASE,
                         params={"language": "de-CH", "limit": per_page,
                                 "skip": skip},
                         headers=DEFAULT_HEADERS, timeout=30)
        r.raise_for_status()
        payload = r.json()
        items = payload.get("results") or payload.get("items") or []
        if not items:
            break
        for it in items:
            term = (it.get("preferredTerm") or it.get("term")
                    or (it.get("labels") or {}).get("de-CH"))
            definition = (it.get("definition")
                          or (it.get("definitions") or {}).get("de-CH"))
            if term and definition:
                entries.append(make_entry(str(term), str(definition),
                                          "CH", source_key,
                                          meta={"termdat_id": it.get("id")}))
            if max_items and len(entries) >= max_items:
                return entries
        skip += per_page
        time.sleep(sleep_s)  # не долбить админский API
        if len(items) < per_page:
            break
    return entries
