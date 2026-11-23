# Тесты браузерной стратегии Termdat (без реальной сети).

from src.dictionaries import browser, registry, termdat
from src.dictionaries.sources import SourceSpec


class FakeResponse:
    def __init__(self, url, payload, status=200, ctype="application/json"):
        self.url = url
        self._payload = payload
        self.status = status
        self.headers = {"content-type": ctype}

    def json(self):
        return self._payload


class FakeLocator:
    def __init__(self, visible_count=0, on_click=None):
        self._count = visible_count
        self._on_click = on_click
        self.first = self

    def count(self):
        return self._count

    def is_visible(self):
        return self._count > 0

    def click(self):
        if self._on_click:
            self._on_click()
        self._count = max(0, self._count - 1)


class FakeKeyboard:
    def __init__(self, on_enter=None):
        self._on_enter = on_enter

    def press(self, key):
        if key == "Enter" and self._on_enter:
            self._on_enter()


class FakePage:
    def __init__(self, on_goto=None, on_enter=None, load_more_clicks=0,
                 on_load_more=None, html="<html></html>", has_search=True):
        self._listeners = {}
        self._on_goto = on_goto
        self._html = html
        self._has_search = has_search
        self.keyboard = FakeKeyboard(on_enter=on_enter)
        self._load_more = FakeLocator(load_more_clicks, on_click=on_load_more)
        self.filled = []
        self.waits = []
        self.closed = False

    def on(self, event, fn):
        self._listeners[event] = fn

    def emit_response(self, resp):
        if "response" in self._listeners:
            self._listeners["response"](resp)

    def goto(self, url, wait_until=None, timeout=None):
        assert timeout == 30000
        if self._on_goto:
            self._on_goto(self)

    def locator(self, selector):
        if "search" in selector or "Such" in selector:
            return FakeLocator(1 if self._has_search else 0)
        if "Mehr" in selector:
            return self._load_more
        return FakeLocator(0)

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def wait_for_selector(self, selector, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def content(self):
        return self._html

    def close(self):
        self.closed = True


def _spec():
    return SourceSpec(
        key="ch_termdat",
        title="Termdat BK",
        url="https://termdat.bk.admin.ch/",
        region="CH",
        extraction="termdat_api",
        headless=True,
    )


def test_registry_resolves_termdat_strategy():
    assert registry.resolve(_spec()) is termdat.strategy


def test_termdat_intercepts_xhr_on_load(monkeypatch):
    payload = {
        "results": [
            {"id": 1, "preferredTerm": "Nachrichtendienst", "definition": "Staatlicher Dienst der Schweiz"},
            {"id": 2, "preferredTerm": "Armee", "definition": "Streitkräfte der Eidgenossenschaft"},
        ]
    }
    page = FakePage(on_goto=lambda p: p.emit_response(
        FakeResponse("https://termdat.bk.admin.ch/api/concepts", payload)
    ))
    monkeypatch.setattr(browser, "new_page", lambda: page)

    entries = termdat.strategy.extract(_spec())
    assert len(entries) == 2
    assert {e.term for e in entries} == {"Nachrichtendienst", "Armee"}
    assert all(e.region == "CH" for e in entries)
    assert page.closed is True


def test_termdat_search_and_load_more(monkeypatch):
    page_holder = {}

    def on_enter():
        page_holder["p"].emit_response(FakeResponse(
            "https://termdat.bk.admin.ch/api/search",
            {"items": [{"term": "Sicherheit", "definition": "Schutz vor Gefahren"}]},
        ))

    def on_more():
        page_holder["p"].emit_response(FakeResponse(
            "https://termdat.bk.admin.ch/api/search?page=2",
            {"items": [{"term": "Zivilschutz", "definition": "Schutz der Bevölkerung"}]},
        ))

    page = FakePage(on_enter=on_enter, load_more_clicks=1, on_load_more=on_more)
    page_holder["p"] = page
    monkeypatch.setattr(browser, "new_page", lambda: page)

    entries = termdat.strategy.extract(_spec())
    assert {e.term for e in entries} == {"Sicherheit", "Zivilschutz"}
    assert page.filled and page.filled[0][1] == "Sicherheit"
    assert all(1000 <= w <= 3000 for w in page.waits)


def test_termdat_dom_fallback(monkeypatch):
    html = (
        "<html><body><dl>"
        "<dt>Bundesanwaltschaft</dt><dd>Strafverfolgungsbehörde des Bundes</dd>"
        "<dt>Kantonsrat</dt><dd>Legislative eines Schweizer Kantons</dd>"
        "<dt>Ständerat</dt><dd>Kleine Kammer der Bundesversammlung</dd>"
        "</dl></body></html>"
    )
    page = FakePage(html=html, has_search=False)
    monkeypatch.setattr(browser, "new_page", lambda: page)

    entries = termdat.strategy.extract(_spec())
    assert len(entries) == 3
    assert {e.term for e in entries} == {"Bundesanwaltschaft", "Kantonsrat", "Ständerat"}
