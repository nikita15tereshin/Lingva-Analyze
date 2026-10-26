"""Реестр источников словарей (слово-значение) для парсинга в БД.

Типы extraction:
- html_table   таблица "термин - определение" на странице;
- html_terms   блоки dl/dt/dd или карточки терминов;
- pdf_glossary глоссарий в PDF (извлечение текста + разбор строк);
- termdat_api  Terminology-Datenbank des Bundes (CH), публичный JSON API.

Поле validate у источника:
- None              импорт без дополнительной проверки;
- exclude_de_base   (AT) отбросить термины, которые являются обычной
  немецкой лексикой (германизмы из полицейского глоссария). Список базовых
  стоп-слов расширяется вручную; при сомнении строка попадает в staging со
  статусом pending и решается через UI.

region="ALL" означает, что источник содержит варианты всех трех стран;
термин получает регион по активной вкладке/контексту страницы.
"""

from dataclasses import dataclass


@dataclass
class SourceSpec:
    key: str
    title: str
    url: str
    region: str                      # DE / AT / CH / ALL
    extraction: str                  # см. докстринг модуля
    enabled: bool = True
    headless: bool = False           # рендер через camoufox/playwright
    selector: str | None = None      # CSS таблицы/контейнера, если известен
    validate: str | None = None
    note: str | None = None


SOURCES: list[SourceSpec] = [
    # --- Германия ---
    SourceSpec("de_bpb", "Glossar Innere Sicherheit (bpb)",
               "https://www.bpb.de/themen/innere-sicherheit/dossier-innere-sicherheit/577646/glossar-innere-sicherheit/",
               "DE", "html_terms"),
    SourceSpec("de_ppf_land", "PPF Glossar Deutschland",
               "https://www.ppfgermany.de/glossar/land/deutschland",
               "DE", "html_table"),
    SourceSpec("de_lka_nds_pdf", "Glossar LKA Niedersachsen",
               "https://www.lka.polizei-nds.de/download/76450/Glossar.pdf.pdf",
               "DE", "pdf_glossary"),
    SourceSpec("de_polizei_beratung", "Glossar Polizei (polizei-beratung)",
               "https://www.polizei-beratung.de/themen-und-tipps/staedtebau/glossar/p/",
               "DE", "html_table"),
    SourceSpec("de_polizeifuerdich", "Glossar polizeifuerdich",
               "https://www.polizeifuerdich.de/glossar-liste/",
               "DE", "html_table"),
    SourceSpec("de_lfv_bayern", "Glossar LFV Bayern",
               "https://www.lfv.bayern.de/glossar/",
               "DE", "html_table"),
    SourceSpec("de_vs_bremen", "Glossar Verfassungsschutz Bremen",
               "https://www.verfassungsschutz.bremen.de/oeffentlichkeitsarbeit/glossar-11578",
               "DE", "html_terms"),
    SourceSpec("de_geheimdienste", "Glossar geheimdienste.net",
               "https://www.geheimdienste.net/glossar",
               "DE", "html_terms"),
    SourceSpec("de_vs_bund", "Glossar BfV",
               "https://www.verfassungsschutz.de/DE/service/glossar/glossar_node.html",
               "DE", "html_table", headless=True,
               note="JS-навигация по алфавиту; при отказе static HTML включается headless"),
    SourceSpec("de_vs_bw", "Glossar Verfassungsschutz BW",
               "https://www.verfassungsschutz-bw.de/,Lde/Startseite/Ueber+uns/Glossar",
               "DE", "html_terms"),
    # --- Австрия ---
    SourceSpec("at_justizonline", "Begriffslexikon BMJ",
               "https://justizonline.gv.at/jop/web/begriffslexikon/all",
               "AT", "html_table", headless=True,
               note="SPA на JS, только через браузер"),
    SourceSpec("at_polizeiglossar_pdf", "Polizeiglossar AT",
               "https://www.gemeinsamsicher.at/downloads/polizeiglossar_3_1_nicht_barrierefrei.pdf",
               "AT", "pdf_glossary", validate="exclude_de_base",
               note="Содержит германизмы, обязателен фильтр валидации"),
    # --- Швейцария ---
    SourceSpec("ch_digitaleschweiz", "Security-Finder-Glossar",
               "https://www.digitaleschweiz.ch/markt/security-finder-schweiz/security-finder-glossar/",
               "CH", "html_table"),
    SourceSpec("ch_termdat", "Termdat BK (admin.ch)",
               "https://termdat.admin.ch/rest/v1/concepts?language=de-CH&limit=100",
               "CH", "termdat_api",
               note="termdat.bk.admin.ch — SPA; данные берутся из публичного REST API"),
    # --- Общие (три страны) ---
    SourceSpec("all_ppf", "PPF Glossar DE/AT/CH",
               "https://www.ppfgermany.de/glossar",
               "ALL", "html_table",
               note="Регион термина определяется по активной вкладке страны"),
]

SOURCES_BY_KEY = {s.key: s for s in SOURCES}
