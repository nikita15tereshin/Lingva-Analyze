"""Универсальная HTML-стратегия с доменной конфигурацией селекторов.

Почему не одна функция: на пятнадцати сайтах термины лежат в разных узлах
(<table>, <dl><dt>/<dd>, аккордеоны Bootstrap, карточки div). Универсальный
перебор дает 0..2 пары на сложных верстках и выглядит как «парсер не
работает». Решение: для каждого домена — свой набор селекторов в SELECTORS;
для неизвестного домена — цепочка эвристик (fallback), которая честно
сообщает, если ничего не найдено, вместо пустого молчания.

Рендер двухуровневый: сначала быстрый requests, при пустом результате или
явном headless-флаге источника — переиспользуемый браузер из browser.py.
"""

import re

import requests
from lxml import html as lxml_html

from src.dictionaries.base import (DEFAULT_HEADERS, DictEntry, FetchError,
                                   SourceStrategy, make_entry)
from src.dictionaries.browser import render as browser_render


# Конфиг селекторов по домену. Поля:
#   container — CSS/XPath контейнер пар (опционально);
#   pair_mode — table | dl | accordion | cards;
#   wait      — селектор, которого ждем перед парсингом (для JS-сайтов).
SELECTORS: dict[str, dict] = {
    "www.ppfgermany.de": {"pair_mode": "table", "wait": "table"},
    "www.polizei-beratung.de": {"pair_mode": "table", "wait": "table"},
    "www.polizeifuerdich.de": {"pair_mode": "table", "wait": "table"},
    "www.lfv.bayern.de": {"pair_mode": "table", "wait": "table"},
    "www.digitaleschweiz.ch": {"pair_mode": "table", "wait": "table"},
    "justizonline.gv.at": {"pair_mode": "table", "wait": "table"},
    "www.bpb.de": {"pair_mode": "dl"},
    "www.verfassungsschutz.bremen.de": {"pair_mode": "accordion"},
    "www.geheimdienste.net": {"pair_mode": "dl"},
    "www.verfassungsschutz-bw.de": {"pair_mode": "accordion"},
    "www.verfassungsschutz.de": {"pair_mode": "table", "wait": "table"},
}


def _region_from_row(cells: list[str]) -> str:
    """Для многострановых таблиц PPF: маркеры DE/AT/CH в подписях колонок."""
    joined = " ".join(cells).lower()
    if "\u00d6sterreich" in joined or re.search(r"\bat\b", joined):
        return "AT"
    if "schweiz" in joined or re.search(r"\bch\b", joined):
        return "CH"
    return "DE"


def _is_header_row(cells: list[str]) -> bool:
    """Строки-заголовки таблиц глоссариев (Begriff/Definition и т.п.)."""
    lowered = [c.lower() for c in cells]
    header_words = {"begriff", "terminus", "term", "definition",
                    "erklärung", "bedeutung", "beschreibung"}
    return all(w in header_words or not w for w in lowered) and len(cells) >= 2


def parse_tables(doc, source_key: str, region: str,
                 selector: str | None = None) -> list[DictEntry]:
    """Таблицы <tr><td>Terminus</td><td>Definition</td></tr>."""
    tables = doc.cssselect(selector) if selector else doc.xpath("//table")
    entries: list[DictEntry] = []
    for table in tables:
        rows = table.xpath(".//tr")
        if len(rows) < 2:
            continue
        good = bad = 0
        local: list[DictEntry] = []
        for tr in rows:
            cells = tr.xpath("./td|./th")
            texts = [c.text_content().strip() for c in cells]
            texts = [t for t in texts if t]
            if len(texts) < 2:
                continue
            if _is_header_row(texts):
                continue
            term, definition = texts[0], texts[-1]
            if len(term) > 90 or len(definition) < 3:
                bad += 1
                continue
            good += 1
            row_region = (_region_from_row(texts)
                          if region == "ALL" else region)
            local.append(make_entry(term, definition, row_region, source_key))
        if good >= 3 and good >= bad:
            entries.extend(local)
            break  # первая подходящая таблица — сама легенда страницы
    return entries


def parse_dlists(doc, source_key: str, region: str) -> list[DictEntry]:
    """Классическая словарная разметка dl/dt/dd."""
    entries: list[DictEntry] = []
    for dl in doc.xpath("//dl"):
        current_term = None
        for el in dl:
            text = el.text_content().strip()
            if not text:
                continue
            if el.tag == "dt":
                current_term = text
            elif el.tag == "dd" and current_term:
                entries.append(make_entry(current_term, text,
                                          region, source_key))
                current_term = None
    return entries


def parse_accordions(doc, source_key: str, region: str) -> list[DictEntry]:
    """Аккордеоны gov-сайтов: button[aria-controls=X] + панель #X."""
    entries: list[DictEntry] = []
    for btn in doc.xpath("//button[@aria-controls] | //a[@aria-controls]"):
        panel_id = btn.get("aria-controls")
        term = btn.text_content().strip()
        panels = doc.xpath(f'//*[@id="{panel_id}"]')
        if panels and term and len(term) <= 90:
            definition = panels[0].text_content().strip()
            if len(definition) >= 10:
                entries.append(make_entry(term, definition,
                                          region, source_key))
    return entries


CARD_TERM = re.compile(r"\b(Termin|Begriff)\b", re.I)


def parse_cards(doc, source_key: str, region: str) -> list[DictEntry]:
    """Карточки div с классами term/definition (частый самописный HTML)."""
    entries: list[DictEntry] = []
    for node in doc.xpath(
            '//*[contains(@class,"term") or contains(@class,"glossar")]'):
        cls = (node.get("class") or "").lower()
        if "term" not in cls:
            continue
        term = node.text_content().strip()
        nxt = node.getnext()
        if not term or nxt is None:
            continue
        definition = nxt.text_content().strip()
        if len(term) <= 90 and len(definition) >= 10:
            entries.append(make_entry(term, definition, region, source_key))
    return entries


MODES = {
    "table": parse_tables,
    "dl": parse_dlists,
    "accordion": parse_accordions,
    "cards": parse_cards,
}


def _domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).lower() if m else ""


def parse_html(html_text: str, source_key: str, region: str,
               pair_mode: str | None = None,
               selector: str | None = None) -> list[DictEntry]:
    """Разбор по указанному режиму либо цепочкой эвристик (fallback)."""
    try:
        doc = lxml_html.fromstring(html_text)
    except Exception as e:
        raise FetchError(f"HTML не разбирается ({e})") from e
    if pair_mode and pair_mode in MODES:
        if pair_mode == "table":
            return parse_tables(doc, source_key, region, selector)
        return MODES[pair_mode](doc, source_key, region)
    # fallback: пробуем все режимы, берём первый с содержательным результатом
    for fn in (parse_tables, parse_dlists, parse_accordions, parse_cards):
        entries = fn(doc, source_key, region)
        if len(entries) >= 3:
            return entries
    return []


class HtmlGenericStrategy(SourceStrategy):
    name = "html_generic"

    def fetch_static(self, url: str) -> str:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    def extract(self, spec) -> list[DictEntry]:
        cfg = SELECTORS.get(_domain_of(spec.url), {})
        pair_mode = cfg.get("pair_mode")
        wait = cfg.get("wait") or spec.selector
        region = spec.region

        html_text = ""
        if not spec.headless:
            try:
                html_text = self.fetch_static(spec.url)
            except requests.RequestException:
                html_text = ""
        entries = (parse_html(html_text, spec.key, region, pair_mode,
                              spec.selector) if html_text else [])
        if len(entries) < 3:
            # JS-сайт или статический разбор провалился — идем в браузер
            try:
                html_text = browser_render(spec.url, selector=wait)
            except ImportError as e:
                if entries:
                    return entries
                raise FetchError(
                    f"браузер для headless-рендера не установлен ({e}); "
                    "для JS-источников нужен camoufox или playwright") from e
            except Exception as e:
                if entries:
                    return entries
                raise FetchError(
                    f"рендер {spec.url} не удался: {e!r}") from e
            parsed = parse_html(html_text, spec.key, region, pair_mode,
                                spec.selector)
            if len(parsed) > len(entries):
                entries = parsed
        if not entries:
            raise FetchError(
                f"на {spec.url} не найдено ни одной пары термин-определение; "
                "проверьте селекторы источника в SELECTORS (html_generic.py)")
        return entries


strategy = HtmlGenericStrategy()
