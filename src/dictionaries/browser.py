"""Единая ленивая сессия headless-браузера для всех HTML-стратегий.

Ранее каждый вызов fetch_html_headless запускал и останавливал Camoufox или
Chromium — на прогоне из десяти JS-источников это десять холодных стартов
браузера. Здесь браузер поднимается один раз на процесс и переиспользуется;
закрытие — через close_browser() (или при завершении процесса).

Модуль деградирует честно: если ни camoufox, ни playwright не установлены,
headless_available() возвращает False, а open_browser бросает ImportError —
sync_source помечает источник failed_browser, как и раньше.
"""

import threading

from src.dictionaries.base import DEFAULT_HEADERS, NAV_TIMEOUT_MS

_lock = threading.Lock()
_state: dict = {"browser": None, "playwright": None, "kind": None}


def headless_available() -> bool:
    try:
        import camoufox.sync_api  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _launch():
    """Внутренний запуск браузера: camoufox предпочтительнее chromium."""
    try:
        from camoufox.sync_api import Camoufox
        browser = Camoufox(headless=True)
        browser.start()
        _state["browser"] = browser
        _state["kind"] = "camoufox"
        return browser
    except ImportError:
        pass
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    _state["playwright"] = pw
    _state["browser"] = browser
    _state["kind"] = "chromium"
    return browser


def get_browser():
    with _lock:
        if _state["browser"] is None:
            _launch()
        return _state["browser"], _state["kind"]


def new_page():
    """Страница с общими заголовками; caller обязан закрыть её сам."""
    browser, kind = get_browser()
    headers = {k: v for k, v in DEFAULT_HEADERS.items() if k != "User-Agent"}
    kwargs = {}
    if kind == "chromium":
        kwargs["extra_http_headers"] = headers
    return browser.new_page(**kwargs)


def render(url: str, selector: str | None = None,
           wait_ms: int = 3500) -> str:
    """Открывает url в переиспользуемом браузере, возвращает HTML."""
    page = new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if selector:
            page.wait_for_selector(selector, timeout=wait_ms)
        else:
            page.wait_for_timeout(wait_ms)
        return page.content()
    finally:
        page.close()


def close_browser():
    with _lock:
        if _state["browser"] is not None:
            try:
                _state["browser"].close()
            except Exception:
                pass
        if _state["playwright"] is not None:
            try:
                _state["playwright"].stop()
            except Exception:
                pass
        _state.update({"browser": None, "playwright": None, "kind": None})
