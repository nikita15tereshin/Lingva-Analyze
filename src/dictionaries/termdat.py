"""Браузерная стратегия для Terminology-Datenbank des Bundes (termdat.bk.admin.ch).

Алгоритм:
1. Перехват XHR/JSON ответов через page.on("response", ...) при загрузке страницы.
2. Если XHR пуст — ввод поискового запроса ("Sicherheit") + Enter и ожидание карточек.
3. Цикл кликов по кнопке "Load more / Mehr anzeigen" с антибан-задержками.
4. Fallback на разбор отрендеренного DOM (parse_html), если XHR не отдал JSON.
"""

import random
import re

from src.dictionaries.base import (
    DictEntry,
    FetchError,
    NAV_TIMEOUT_MS,
    SourceStrategy,
    make_entry,
)
from src.dictionaries import browser
from src.dictionaries.html_generic import parse_html

TERMDAT_URL = "https://termdat.bk.admin.ch/"
SEARCH_SELECTORS = (
    "input[type=\"search\"]",
    "input[role=\"searchbox\"]",
    "input[placeholder*=\"Such\"]",
    "input[aria-label*=\"Such\"]",
)
RESULT_SELECTOR = ".result-item, .concept-card, [class*=\"result\"], table tbody tr"
LOAD_MORE_SELECTORS = (
    "button:has-text(\"Mehr\")",
    "button:has-text(\"Load more\")",
    "button:has-text(\"Weitere\")",
    "button[class*=\"load-more\"]",
)
API_URL_HINT = re.compile(r"(/rest/|/api/|concepts|search|entries)", re.I)


def _human_delay(page, min_ms: int = 1000, max_ms: int = 3000) -> None:
    page.wait_for_timeout(random.randint(min_ms, max_ms))


def _parse_api_payload(payload, source_key: str) -> list[DictEntry]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (
            payload.get("results")
            or payload.get("items")
            or payload.get("entries")
            or payload.get("content")
            or []
        )
    else:
        return []

    entries: list[DictEntry] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        labels = it.get("labels") if isinstance(it.get("labels"), dict) else {}
        defs = it.get("definitions") if isinstance(it.get("definitions"), dict) else {}
        term = (
            it.get("preferredTerm")
            or it.get("term")
            or it.get("designation")
            or labels.get("de-CH")
            or labels.get("de")
        )
        definition = (
            it.get("definition")
            or it.get("description")
            or defs.get("de-CH")
            or defs.get("de")
        )
        if term and definition:
            entries.append(
                make_entry(
                    str(term),
                    str(definition),
                    "CH",
                    source_key,
                    meta={"termdat_id": it.get("id")},
                )
            )
    return entries


class TermdatStrategy(SourceStrategy):
    name = "termdat_api"

    def extract(self, spec, query: str = "Sicherheit", max_clicks: int = 20) -> list[DictEntry]:
        url = spec.url if getattr(spec, "url", None) else TERMDAT_URL
        captured: dict[str, DictEntry] = {}

        def _collect(items: list[DictEntry]) -> int:
            added = 0
            for e in items:
                key = e.term.lower()
                if e.term and key not in captured:
                    captured[key] = e
                    added += 1
            return added

        def _on_response(response) -> None:
            try:
                if getattr(response, "status", 0) != 200:
                    return
                headers = {k.lower(): v for k, v in (getattr(response, "headers", None) or {}).items()}
                ctype = headers.get("content-type", "")
                resp_url = getattr(response, "url", "")
                if "json" not in ctype.lower() and not API_URL_HINT.search(resp_url):
                    return
                payload = response.json()
                _collect(_parse_api_payload(payload, spec.key))
            except Exception:
                pass

        try:
            page = browser.new_page()
        except ImportError as e:
            raise FetchError(
                f"браузер для headless-рендера не установлен ({e}); "
                "для Termdat нужен playwright или camoufox"
            ) from e

        try:
            if hasattr(page, "on"):
                page.on("response", _on_response)

            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            _human_delay(page)

            if not captured:
                self._run_search(page, query)

            self._click_load_more(page, max_clicks=max_clicks)

            if not captured:
                html_text = page.content()
                _collect(parse_html(html_text, spec.key, "CH"))
        except FetchError:
            raise
        except Exception as e:
            if not captured:
                raise FetchError(f"Termdat ({url}) не удалось разобрать: {e!r}") from e
        finally:
            page.close()

        if not captured:
            raise FetchError(
                f"Termdat ({url}): не найдено ни одной пары термин-определение "
                "(ни через XHR, ни через DOM)"
            )
        return list(captured.values())

    def _run_search(self, page, query: str) -> None:
        for sel in SEARCH_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    page.fill(sel, query)
                    page.keyboard.press("Enter")
                    try:
                        page.wait_for_selector(RESULT_SELECTOR, timeout=10000)
                    except Exception:
                        pass
                    _human_delay(page)
                    return
            except Exception:
                continue

    def _click_load_more(self, page, max_clicks: int = 20) -> None:
        for _ in range(max_clicks):
            clicked = False
            for sel in LOAD_MORE_SELECTORS:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.click()
                        _human_delay(page)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                break


strategy = TermdatStrategy()
