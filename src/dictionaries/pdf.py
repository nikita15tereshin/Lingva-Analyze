"""Стратегия для PDF-глоссариев (DE-3 LKA Niedersachsen, AT-2 Polizeiglossar).

Почему не браузер: PDF — не HTML-страница, page.goto на нем бесполезен.
Скачиваем байты через HTTP и разбираем текстовые слои PyMuPDF (fitz).

Два макета глоссариев в списке источников:
1) "Terminus: определение" в одной строке;
2) "Terminus" отдельной короткой строкой, определение — следующая(ые)
   строки до нового термина или заголовка раздела.

Все ошибки сети/парсинга упаковываются в FetchError с понятным текстом —
sync_source пишет его в DictionarySource.last_error без traceback-мусора.
"""

import re

import requests

from src.dictionaries.base import (DEFAULT_HEADERS, DictEntry, FetchError,
                                   SourceStrategy, make_entry)

# Короткая строка-кандидат в термины: слово с заглавной (умлауты/ß), дефисы,
# точки, косая черта, пробелы внутри; длина до 80 символов.
TERM_CANDIDATE = re.compile(r"[A-ZÄÖÜ][\wÄÖÜäöüß\-/. ]{2,79}")
# Строка вида "Terminus: определение" / "Terminus – определение".
TERM_LINE = re.compile(
    r"^(?P<term>[A-ZÄÖÜ][\wÄÖÜäöüß/. ()]{1,80}?)"
    r"(?P<sep>:|\u2013|\u2014|(?<= )-(?= ))\s+(?P<def>\S.*)$")
# Пометки страниц-помехи: колонтитулы, нумерация, «Seite 12», оглавление.
NOISE_LINE = re.compile(
    r"^(seite\s+\d+|\d{1,3}|inhaltsverzeichnis|legende|abk[.]?r[.]?zung)$",
    re.I)


def _extract_text(pdf_bytes: bytes) -> list[str]:
    try:
        import fitz  # pymupdf
    except ImportError as e:  # pragma: no cover - окружение без зависимостей
        raise FetchError(f"pymupdf (fitz) не установлен: {e}") from e
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise FetchError(f"файл не является корректным PDF: {e!r}") from e
    lines: list[str] = []
    try:
        if doc.is_encrypted and not doc.authenticate(b""):
            # защищённый паролем глоссарий — попытка пустого пароля уже была
            raise FetchError("PDF зашифрован, извлечение текста невозможно")
        for page in doc:
            for raw in page.get_text("text").splitlines():
                s = raw.strip()
                if s and not NOISE_LINE.match(s):
                    lines.append(s)
    finally:
        doc.close()
    if not lines:
        raise FetchError("в PDF нет извлекаемого текста (скан-картинки?)")
    return lines


def parse_pdf_lines(lines: list[str], region: str, source_key: str) -> list[DictEntry]:
    entries: list[DictEntry] = []
    pending_term: str | None = None
    buf: list[str] = []

    def flush():
        nonlocal pending_term, buf
        if pending_term and buf:
            definition = " ".join(buf).strip()
            if len(definition) >= 3:
                entries.append(make_entry(pending_term, definition,
                                          region, source_key))
        pending_term, buf = None, []

    for line in lines:
        m = TERM_LINE.match(line)
        if m:
            flush()
            entries.append(make_entry(m.group("term"), m.group("def"),
                                      region, source_key))
            continue
        is_new_term = (len(line) <= 80 and TERM_CANDIDATE.fullmatch(line)
                       and not line.endswith("."))
        if pending_term is not None:
            if is_new_term:
                # предыдущий термин остался без определения (заголовок раздела)
                flush()
                pending_term = line
            else:
                buf.append(line)
            continue
        if is_new_term:
            pending_term = line
    flush()

    seen: set[str] = set()
    out = []
    for e in entries:
        key = e.term.lower()
        if not e.term or key in seen or len(e.definition) < 3:
            continue
        seen.add(key)
        out.append(e)
    return out


class PdfGlossaryStrategy(SourceStrategy):
    name = "pdf_glossary"

    def download(self, url: str, timeout: int = 60) -> bytes:
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise FetchError(f"не удалось скачать PDF ({url}): {e}") from e
        ctype = r.headers.get("content-type", "")
        if "pdf" not in ctype and not r.content.startswith(b"%PDF"):
            raise FetchError(
                f"ссылка отдает не PDF (content-type={ctype!r}); "
                "возможно, страница отдачи требует cookie или переехала")
        return r.content

    def extract(self, spec) -> list[DictEntry]:
        pdf_bytes = self.download(spec.url)
        lines = _extract_text(pdf_bytes)
        entries = parse_pdf_lines(lines, spec.region, spec.key)
        if len(entries) < 3:
            raise FetchError(
                f"распознано только {len(entries)} пар термин-определение; "
                "проверьте макет глоссария вручную")
        return entries


strategy = PdfGlossaryStrategy()
