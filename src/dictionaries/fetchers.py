"""Извлечение пар "термин - определение" из источников словарей.

Конвейер: fetch (requests, опционально camoufox/playwright для JS-сайтов) ->
парсер конкретного типа -> список DictEntry -> валидация -> staging в БД.

Playwright/camoufox подключаются лениво: если пакет не установлен, модуль
работает только с HTTP-источниками и честно сообщает об этом вызывающему коду.
"""

import re
import time
from dataclasses import dataclass, field

import requests
from lxml import html as lxml_html

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de-CH;q=0.9,de;q=0.8",
}


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


# ---------------------------------------------------------------- fetch

def fetch_html(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def fetch_pdf_bytes(url: str, timeout: int = 60) -> bytes:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.content


def fetch_html_headless(url: str, selector: str | None = None,
                        wait_ms: int = 3500) -> str:
    """Рендер через camoufox (предпочтительно) или chromium playwright.

    Навигация ограничена таймаутом 30 секунд: зависший сайт не должен
    вешать процесс синхронизации словарей целиком.
    """
    try:
        from camoufox.sync_api import Camoufox
        with Camoufox(headless=True) as browser:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if selector:
                page.wait_for_selector(selector, timeout=wait_ms)
            else:
                page.wait_for_timeout(wait_ms)
            return page.content()
    except ImportError:
        pass
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(extra_http_headers={
                k: v for k, v in DEFAULT_HEADERS.items() if k != "User-Agent"})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if selector:
                page.wait_for_selector(selector, timeout=wait_ms)
            else:
                page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            browser.close()


# ------------------------------------------------------------- parsers

def parse_html_table(html_text: str, source_key: str, region: str,
                     selector: str | None = None) -> list[DictEntry]:
    """Таблицы вида <tr><td>Terminus</td><td>Definition</td></tr>.

    Берется первая двухколоночная (или 3+ колоночная, где колонка 1 — термин,
    последняя — определение) таблица; строки-заголовки отбрасываются.
    """
    doc = lxml_html.fromstring(html_text)
    tables = doc.cssselect(selector) if selector else doc.xpath("//table")
    entries: list[DictEntry] = []
    for table in tables:
        rows = table.xpath(".//tr")
        if len(rows) < 2:
            continue
        good = 0
        bad = 0
        local: list[DictEntry] = []
        for tr in rows:
            cells = tr.xpath("./td|./th")
            texts = [c.text_content().strip() for c in cells]
            texts = [t for t in texts if t]
            if len(texts) < 2:
                continue
            term, definition = texts[0], texts[-1]
            if len(term) > 90 or len(definition) < 3:
                bad += 1
                continue
            good += 1
            local.append(DictEntry(normalize_term(term),
                                   clean_definition(definition),
                                   region if region != "ALL" else _region_from_row(texts),
                                   source_key))
        if good >= 3 and good >= bad:
            entries.extend(local)
            break  # первая подходящая таблица — сама легенда страницы
    return entries


def _region_from_row(cells: list[str]) -> str:
    """Для многострановых таблиц PPF: ищем маркеры DE/AT/CH в подписях."""
    joined = " ".join(cells).lower()
    if "\u00d6sterreich" in joined or "at:" in joined:
        return "AT"
    if "schweiz" in joined or "ch:" in joined:
        return "CH"
    return "DE"


def parse_html_terms(html_text: str, source_key: str, region: str) -> list[DictEntry]:
    """Блоки dl/dt/dd, а также аккордеоны (кнопка-термин + панель определения)."""
    doc = lxml_html.fromstring(html_text)
    entries: list[DictEntry] = []
    for dl in doc.xpath("//dl"):
        current_term = None
        for el in dl:
            tag = el.tag
            text = el.text_content().strip()
            if not text:
                continue
            if tag == "dt":
                current_term = text
            elif tag == "dd" and current_term:
                entries.append(DictEntry(normalize_term(current_term),
                                         clean_definition(text), region, source_key))
                current_term = None
    if len(entries) >= 3:
        return entries

    # аккордеон-разметка gov-сайтов: button[aria-controls=X] + div#X
    entries = []
    for btn in doc.xpath("//button[@aria-controls]"):
        panel_id = btn.get("aria-controls")
        term = btn.text_content().strip()
        panels = doc.xpath(f'//*[@id="{panel_id}"]')
        if panels and term and len(term) <= 90:
            definition = clean_definition(panels[0].text_content())
            if len(definition) >= 10:
                entries.append(DictEntry(normalize_term(term), definition,
                                         region, source_key))
    return entries


TERM_LINE = re.compile(
    r"^(?P<term>(?:[A\u00c4\u00d6\u00dcZ\u00df][\w\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df\-/. ()]{1,80}))[:\u2013\u2014-]\s+(?P<def>\S.*)$"
)


def parse_pdf_glossary(pdf_bytes: bytes, source_key: str, region: str) -> list[DictEntry]:
    """Разбор PDF-глоссария.

    Поддерживает два макета: "Terminus: определение" в одной строке и
    "Terminus" отдельной строкой с определением на следующей. Мусорные
    пары (термин длинный/определение пустое) отсекаются, дубли внутри
    файла удаляются по термину.
    """
    import fitz  # pymupdf
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    lines: list[str] = []
    for page in doc:
        for raw in page.get_text("text").splitlines():
            s = raw.strip()
            if s:
                lines.append(s)
    doc.close()

    entries: list[DictEntry] = []
    pending_term: str | None = None
    for line in lines:
        m = TERM_LINE.match(line)
        if m:
            pending_term = None
            entries.append(_mk(m.group("term"), m.group("def"), region, source_key))
            continue
        if pending_term is not None:
            if re.fullmatch(r"(?:[A\u00c4\u00d6\u00dcZ\u00df]\w[\w\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df\-/. ()]{1,79})|(?:\d+[\).\s].*)", line):
                # следующая строка похожа на новый термин или нумерованный пункт —
                # предыдущий термин остался без определения
                pending_term = line if line[:1].isalpha() else None
                continue
            entries.append(_mk(pending_term, line, region, source_key))
            pending_term = None
            continue
        if len(line) <= 80 and re.fullmatch(r"[A\u00c4\u00d6\u00dc\u00df][\w\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df\-/. ]{2,79}", line):
            pending_term = line
    # дедупликация по термину внутри файла
    seen: set[str] = set()
    out = []
    for e in entries:
        if not e.term or e.term.lower() in seen or len(e.definition) < 3:
            continue
        seen.add(e.term.lower())
        out.append(e)
    return out


def _mk(term: str, definition: str, region: str, source_key: str) -> DictEntry:
    return DictEntry(normalize_term(term), clean_definition(definition), region, source_key)


TERM_DAT_BASE = "https://termdat.admin.ch/rest/v1/concepts"


def parse_termdat(source_key: str, per_page: int = 100, max_items: int | None = None,
                  sleep_s: float = 0.4) -> list[DictEntry]:
    """Публичный JSON API Terminology-Datenbank des Bundes (de-CH)."""
    entries: list[DictEntry] = []
    skip = 0
    while True:
        r = requests.get(TERM_DAT_BASE,
                         params={"language": "de-CH", "limit": per_page, "skip": skip},
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
                entries.append(DictEntry(normalize_term(str(term)),
                                         clean_definition(str(definition)),
                                         "CH", source_key,
                                         meta={"termdat_id": it.get("id")}))
            if max_items and len(entries) >= max_items:
                return entries
        skip += per_page
        time.sleep(sleep_s)  # не долбить админский API
        if len(items) < per_page:
            break
    return entries


# --------------------------------------------------------------- dispatch

def extract_entries(spec, headless: bool | None = None) -> list[DictEntry]:
    """Точка входа: спецификация источника -> список пар слово-значение."""
    use_headless = spec.headless if headless is None else headless
    if spec.extraction == "termdat_api":
        return parse_termdat(spec.key)
    if spec.extraction == "pdf_glossary":
        return parse_pdf_glossary(fetch_pdf_bytes(spec.url), spec.key, spec.region)
    html_text = ""
    if use_headless:
        html_text = fetch_html_headless(spec.url, spec.selector)
    else:
        try:
            html_text = fetch_html(spec.url)
        except requests.RequestException:
            if not spec.headless:
                raise
        if len(parse_html_table(html_text, spec.key, spec.region, spec.selector)) < 3 and \
           len(parse_html_terms(html_text, spec.key, spec.region)) < 3 and spec.headless:
            html_text = fetch_html_headless(spec.url, spec.selector)
    entries = parse_html_table(html_text, spec.key, spec.region, spec.selector)
    if not entries:
        entries = parse_html_terms(html_text, spec.key, spec.region)
    return entries
