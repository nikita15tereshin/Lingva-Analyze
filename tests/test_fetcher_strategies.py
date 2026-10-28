"""Тесты стратегий извлечения словарей после рефакторинга fetchers.py.

Сеть не трогаем: requests.get и браузерный рендер подменяются заглушками.
Проверяем три вещи:
1) PDF-стратегия скачивает байты, разбирает оба макета глоссариев и
   выдает внятную FetchError вместо падения/пустого результата;
2) HTML-стратегия использует доменную конфигурацию селекторов и падает
   с сообщением, когда пар ничего не нашел (раньше молча возвращала []);
3) registry подключает стратегии по полю spec.extraction.
"""

import pytest

from src.dictionaries import html_generic, pdf, registry
from src.dictionaries.base import DictEntry, FetchError
from src.dictionaries.sources import SourceSpec


class FakeResponse:
    def __init__(self, content=b"", text="", json_data=None, ctype=""):
        self.content = content
        self.text = text
        self._json = json_data or {}
        self.headers = {"content-type": ctype}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


def _spec(**kw):
    base = dict(key="t_test", title="Test", url="https://example.test/glossar",
                region="DE", extraction="html_table")
    base.update(kw)
    return SourceSpec(**base)


# ------------------------------------------------------------- pdf strategy

PDF_ONE_LINE = """
Gefährder: Person mit politisch motivierter Gewaltbereitschaft
Phänomenbereich – Phänomenfelder extremistischer Bestrebungen
Seite 12
"""

PDF_TWO_LINE = """
Ausschreibung
Öffentliche Aufforderung zur Angebotseinholung bei Vergabeverfahren
Bürgerwehren
Zusammenschlüsse von Privatpersonen ohne behördliche Legitimation
Landesamt
Behörde der mittleren Ebene innerhalb einer Landespolizei
Inhaltsverzeichnis
"""


def test_pdf_strategy_parses_both_layouts(monkeypatch):
    # макет 1: "Terminus: определение" в одной строке
    lines1 = [l for l in PDF_ONE_LINE.splitlines() if l.strip()]
    monkeypatch.setattr(pdf, "_extract_text", lambda b: lines1)
    monkeypatch.setattr(pdf.PdfGlossaryStrategy, "download",
                        lambda self, url, timeout=60: b"%PDF-1.4 fake")
    entries = pdf.strategy.extract(_spec(extraction="pdf_glossary"))
    terms = {e.term.lower() for e in entries}
    assert "gefährder" in terms
    assert "phänomenbereich" in terms
    # шумовая строка "Seite 12" не должна стать термином
    assert not any("seite" in t for t in terms)


def test_pdf_strategy_parses_two_line_layout(monkeypatch):
    # макет 2: термин отдельной строкой, определение следующей строкой
    lines2 = [l for l in PDF_TWO_LINE.splitlines() if l.strip()]
    monkeypatch.setattr(pdf, "_extract_text", lambda b: lines2)
    monkeypatch.setattr(pdf.PdfGlossaryStrategy, "download",
                        lambda self, url, timeout=60: b"%PDF-1.4 fake")
    entries = pdf.strategy.extract(_spec(extraction="pdf_glossary"))
    pairs = {e.term: e.definition for e in entries}
    assert "Ausschreibung" in pairs
    assert "Angebotseinholung" in pairs["Ausschreibung"]
    assert "Bürgerwehren" in pairs
    assert "Landesamt" in pairs


def test_pdf_download_rejects_html(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(content=b"<html>404</html>",
                            ctype="text/html")
    monkeypatch.setattr(pdf.requests, "get", fake_get)
    with pytest.raises(FetchError, match="не PDF"):
        pdf.strategy.download("https://example.test/Glossar.pdf")


def test_pdf_too_few_entries_raises(monkeypatch):
    monkeypatch.setattr(pdf, "_extract_text", lambda b: ["Ein Begriff"])
    monkeypatch.setattr(pdf.PdfGlossaryStrategy, "download",
                        lambda self, url, timeout=60: b"x")
    with pytest.raises(FetchError, match="распознано только"):
        pdf.strategy.extract(_spec(extraction="pdf_glossary"))


# ---------------------------------------------------------- html strategy

TABLE_HTML = """
<html><body><table>
<tr><th>Begriff</th><th>Definition</th></tr>
<tr><td>Marschgelöbnis</td><td>militärisches Zeremoniell in der Schweiz</td></tr>
<tr><td>Zustellungsorgan</td><td>Behörde für die Zustellung von Schriften</td></tr>
<tr><td>Gemeinderat</td><td>Exekutive einer Gemeinde in AT und CH</td></tr>
</table></body></html>
"""

DL_HTML = """
<html><body>
<dl>
<dt>Verfassungsschutz</dt><dd>Aufklärung extremistischer Bestrebungen</dd>
<dt>Nachrichtendienst</dt><dd>Institution der äußeren Sicherheit</dd>
<dt>Tarnorganisation</dt><dd>Verein nach außen legitimer Zweckbindung</dd>
</dl></body></html>
"""


def test_html_uses_domain_config(monkeypatch):
    spec = _spec(url="https://www.ppfgermany.de/glossar/land/deutschland",
                 extraction="html_table")
    monkeypatch.setattr(html_generic.HtmlGenericStrategy, "fetch_static",
                        lambda self, url: TABLE_HTML)
    entries = html_generic.strategy.extract(spec)
    assert len(entries) == 3
    assert entries[0].region == "DE"


def test_html_all_region_from_row(monkeypatch):
    html = """<html><table>
<tr><td>Bundesheer</td><td>Österreich</td><td>das Bundesheer ist AT</td></tr>
<tr><td>Schweizer Armee</td><td>Schweiz</td><td>Armee der Schweiz</td></tr>
<tr><td>Bundeswehr</td><td>Deutschland</td><td>Streitkräfte DE</td></tr>
</table></html>"""
    spec = _spec(url="https://www.ppfgermany.de/glossar", region="ALL",
                 extraction="html_table")
    monkeypatch.setattr(html_generic.HtmlGenericStrategy, "fetch_static",
                        lambda self, url: html)
    entries = html_generic.strategy.extract(spec)
    regions = {e.region for e in entries}
    assert {"AT", "CH", "DE"} <= regions


def test_html_dl_mode(monkeypatch):
    spec = _spec(url="https://www.bpb.de/themen/glossar",
                 extraction="html_terms")
    monkeypatch.setattr(html_generic.HtmlGenericStrategy, "fetch_static",
                        lambda self, url: DL_HTML)
    entries = html_generic.strategy.extract(spec)
    assert {e.term for e in entries} == {"Verfassungsschutz",
                                         "Nachrichtendienst",
                                         "Tarnorganisation"}


def test_html_empty_when_nothing_found(monkeypatch):
    spec = _spec(url="https://unknown.example/x", extraction="html_table")
    monkeypatch.setattr(html_generic.HtmlGenericStrategy, "fetch_static",
                        lambda self, url: "<html><body><p>js only</p></body></html>")
    monkeypatch.setattr(html_generic, "browser_render",
                        lambda url, selector=None, **kw:
                        pytest.fail("браузер дергается только при headless/мало данных")
                        if False else "<html></html>")
    with pytest.raises(FetchError, match="не найдено ни одной пары"):
        html_generic.strategy.extract(spec)


def test_html_falls_back_to_browser(monkeypatch):
    spec = _spec(url="https://justizonline.gv.at/jop/web/begriffslexikon/all",
                 region="AT", extraction="html_table", headless=True)
    calls = []
    monkeypatch.setattr(html_generic, "browser_render",
                        lambda url, selector=None, **kw:
                        calls.append((url, selector)) or TABLE_HTML)
    entries = html_generic.strategy.extract(spec)
    assert len(entries) == 3
    assert calls and calls[0][1] == "table"  # wait-селектор из конфига домена


# ---------------------------------------------------------------- registry

def test_registry_dispatch():
    p = registry.resolve(_spec(extraction="pdf_glossary"))
    h = registry.resolve(_spec(extraction="html_table"))
    assert p is pdf.strategy
    assert h is html_generic.strategy


def test_extract_entries_headless_override(monkeypatch):
    seen = {}

    def fake_extract(self, spec):
        seen["headless"] = spec.headless
        return [DictEntry("a", "b", "DE", "c")]
    monkeypatch.setattr(html_generic.HtmlGenericStrategy, "extract",
                        fake_extract)
    registry.extract_entries(_spec(headless=False), headless=True)
    assert seen["headless"] is True
