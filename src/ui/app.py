import io
import json
import os
import sys

import pandas as pd
import hashlib as _hl
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text as sa_text

from src.parser.reader import extract_and_normalize
from src.nlp.processor import process_text
from src.db.session import SessionLocal, engine
from src.db.models import Base, Document, SemanticShift
from src.db.crud import (
    create_document,
    save_nlp_data_to_db,
    get_document_index_from_db,
    get_frequency_table,
)
from src.analysis.context import get_contexts_for_lemma
from src.analysis.matcher import classify_unique_words
from src.analysis.llm import analyze_semantic_context_stream
from src.query import engine as query_engine
from src.query.defaults import seed_defaults

# --- Настройка страницы ---
st.set_page_config(page_title="Lingva-Analyze", layout="wide")


@st.cache_resource
def init_database():
    """Гарантирует наличие схемы даже без прогнанных миграций alembic."""
    Base.metadata.create_all(bind=engine)
    return True


init_database()

# --- Сайдбар: загрузка и выбор документа ---
st.sidebar.header("1. Загрузить документ")

uploaded_file = st.sidebar.file_uploader(
    "Выберите TXT, PDF или DOCX", type=["txt", "pdf", "docx"]
)

col_c, col_t = st.sidebar.columns(2)
country_code = col_c.selectbox("Страна", ["", "DE", "AT", "CH"])
external_code = col_t.text_input("Код (DE-01)", value="", max_chars=16)
doc_type = st.sidebar.text_input("Тип (отчет, речь…)", value="")

if uploaded_file is not None:
    if st.sidebar.button("Обработать"):
        with st.spinner("Извлекаем текст..."):
            try:
                raw_bytes = uploaded_file.getvalue()
                extracted_text = extract_and_normalize(io.BytesIO(raw_bytes), uploaded_file.name)

                db = SessionLocal()
                try:
                    doc = create_document(
                        db,
                        filename=uploaded_file.name,
                        country=country_code or None,
                        external_code=external_code.strip() or None,
                        doc_type=doc_type.strip() or None,
                    )
                    with st.spinner("NLP-анализ (лемматизация)..."):
                        nlp_results = process_text(extracted_text)
                    save_nlp_data_to_db(db, doc.id, nlp_results)
                    st.success(f"Сохранено в БД! document_id = {doc.id}")
                finally:
                    db.close()
            except Exception as e:
                st.error(f"Ошибка обработки: {e}")

db = SessionLocal()
try:
    docs = db.query(Document).order_by(Document.id.desc()).all()
    options = [f"{d.id}: {d.filename}" + (f" [{d.external_code}]" if d.external_code else "") for d in docs]
finally:
    db.close()

if not options:
    st.info("Загрузите первый документ через сайдбар.")
    st.stop()

selected_idx = st.sidebar.selectbox("2. Активный документ", range(len(options)), format_func=lambda i: options[i])
active_doc_id = docs[selected_idx].id

# --- Основная область ---
st.title("Lingva-Analyze Dashboard")
st.caption(f"Активный документ ID: {active_doc_id}")

tab_lexicon, tab_kwic, tab_matrix, tab_dict, tab_llm = st.tabs(
    ["Лексический индекс", "KWIC-конкорданс", "Матрица параметров", "Словари", "LLM"]
)

with tab_lexicon:
    index_data = get_document_index_from_db(db := SessionLocal(), active_doc_id)
    freq_rows = get_frequency_table(db, active_doc_id)
    db.close()

    df = pd.DataFrame(freq_rows)
    max_freq = st.number_input("Прикол А: показать только леммы с частотой не выше", value=5, min_value=1)
    filtered = df[df["count"] <= max_freq] if not df.empty else df
    st.dataframe(filtered, use_container_width=True)
    st.write(f"Уникальных лемм: {len(index_data)}")

    # Классификация уникальных слов по региональному словарю
    unique_words = list(index_data.keys())
    _cdb = SessionLocal()
    try:
        result = classify_unique_words(_cdb, unique_words)
    finally:
        _cdb.close()

    matches = (
        [{"lemma": m["lemma"], "meaning": m.get("standard_de", ""), "type": "Австрицизм"}
         for m in result["AT_matches"]]
        + [{"lemma": m["lemma"], "meaning": m.get("standard_de", ""), "type": "Гельветизм"}
           for m in result["CH_matches"]]
    )
    st.write(f"Регионализмов в документе: {len(matches)}")

    with st.expander("Найденные слова и их контексты"):
        if not matches:
            st.write("Совпадений со словарем нет.")
        else:
            sel = st.selectbox(
                "Слово",
                [m["lemma"] for m in matches],
                key="lex_word_select",
            )
            meaning = next((m["meaning"] for m in matches if m["lemma"] == sel), "")
            if meaning:
                st.caption(f"Значение по словарю: {meaning}")
            _sdb = SessionLocal()
            try:
                contexts = get_contexts_for_lemma(_sdb, sel, active_doc_id)
            finally:
                _sdb.close()
            if not contexts:
                st.write("Контексты не найдены.")
            for ctx in contexts[:15]:
                st.markdown(f"**{ctx['word_form']}** (позиция {ctx['position']})")
                st.write(ctx["target_sentence"])
                prev_next = ctx["full_context"].replace(ctx["target_sentence"], "").strip()
                if prev_next:
                    st.caption(f"Соседние предложения: {prev_next[:300]}")

with tab_kwic:
    lemma_query = st.text_input("Лемма для поиска контекстов", value="Bundeswehr")
    if lemma_query and st.button("Показать KWIC"):
        contexts = get_contexts_for_lemma(SessionLocal(), lemma_query, active_doc_id)
        if not contexts:
            st.write("Ничего не найдено в текущем документе.")
        for ctx in contexts[:20]:
            st.markdown(f"**{ctx['word_form']}** (позиция {ctx['position']})")
            st.write(ctx["target_sentence"])

            _key = _hl.md5(f"{lemma_query}_{ctx['position']}_{ctx['word_form']}".encode()).hexdigest()[:12]
            if st.button("Объяснить через LLM", key=f"llm_{_key}"):
                placeholder = st.empty()
                full_response = ""
                for chunk in analyze_semantic_context_stream(
                    word=lemma_query,
                    sentence=ctx["target_sentence"],
                    expected_region="AT/CH/DE",
                ):
                    full_response += chunk
                    placeholder.markdown(full_response + "▌")
                placeholder.markdown(full_response)

with tab_matrix:
    st.caption("Пункт 4.4 ТЗ: матрица сравнительного анализа P1–P9 + кастомные параметры")

    if st.button("Инициализировать пресеты P1–P9"):
        counts = seed_defaults(SessionLocal())
        st.success(
            f"Создано параметров: {counts['parameters']}, пар замен: {counts['lexical_pairs']}, "
            f"омонимов P7: {counts.get('semantic_shifts', 0)}")

    params_db = SessionLocal()
    try:
        from src.db.models import QueryParameter
        parameters = params_db.query(QueryParameter).order_by(QueryParameter.code).all()
        param_names = {p.code: f"{p.code} — {p.name} ({p.query_type})" for p in parameters}
    finally:
        params_db.close()

    if not parameters:
        st.info("Нажмите «Инициализировать пресеты» выше.")
    else:
        sel_code = st.selectbox("Параметр", list(param_names.keys()), format_func=lambda c: param_names[c])

        countries_sel = st.multiselect("Ограничить странами", ["DE", "AT", "CH"], default=[])
        if st.button("Прогнать по корпусу"):
            run_db = SessionLocal()
            try:
                param = run_db.query(QueryParameter).filter(QueryParameter.code == sel_code).first()
                res = query_engine.run_parameter(run_db, param, None, countries_sel or None)
                st.success(f"Документов: {res['documents']}, попаданий: {res['hits']}")
            finally:
                run_db.close()

        stats_db = SessionLocal()
        try:
            by_country = query_engine.statistics_by_country(stats_db, sel_code)
            by_marker = query_engine.statistics_by_marker(stats_db, sel_code)
            rows = query_engine.hits_with_context(stats_db, sel_code)
        finally:
            stats_db.close()

        if by_country:
            st.bar_chart(pd.DataFrame(by_country).set_index("country"))
        if by_marker:
            st.dataframe(pd.DataFrame(by_marker), use_container_width=True)
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
            csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
            st.download_button("Скачать CSV", csv, file_name=f"{sel_code}.csv", mime="text/csv")

        param_row = None
        look_db = SessionLocal()
        try:
            param_row = look_db.query(QueryParameter).filter(
                QueryParameter.code == sel_code).first()
            is_semantic = param_row is not None and param_row.query_type == "SEMANTIC_SHIFT"
        finally:
            look_db.close()

        if is_semantic:
            st.divider()
            st.caption("P7: гибрид. Уверенные случаи разметил код (rule), спорные ждут LLM (llm_pending)")
            from src.analysis.semantic import pending_hits, disambiguate_pending
            disp_db = SessionLocal()
            try:
                pend = pending_hits(disp_db, sel_code)
                st.write(f"Спорных вхождений после прогона: {len(pend)}")
                if pend:
                    st.dataframe(pd.DataFrame(pend), use_container_width=True)
                    if st.button("Разобрать спорные через LLM (один пакетный запрос)"):
                        try:
                            stats = disambiguate_pending(disp_db, sel_code)
                            st.success(
                                f"Всего: {stats['total']}, определено: {stats['resolved']}, "
                                f"unknown: {stats['unknown']}, без ответа: {stats['failed']}")
                        except RuntimeError as exc:
                            st.error(str(exc))
                else:
                    st.info("Спорных нет или параметр еще не прогонялся по корпусу.")

                shifts = disp_db.query(SemanticShift).order_by(
                    SemanticShift.word, SemanticShift.country).all()
                st.caption("Справочник омонимов (правится здесь же, кнопкой ниже)")
                if shifts:
                    st.dataframe(pd.DataFrame([
                        {"word": s.word, "страна": s.country, "значение": s.meaning,
                         "маркеры": s.collocations or ""} for s in shifts
                    ]), use_container_width=True)
                with st.expander("Добавить/обновить омоним"):
                    new_word = st.text_input("Слово (лемма)", key="ss_word")
                    new_country = st.selectbox("Страна значения", ["DE", "AT", "CH"], key="ss_country")
                    new_meaning = st.text_input("Значение", key="ss_meaning")
                    new_cols = st.text_input(
                        "Колокации-маркеры (через запятую, нижний регистр)", key="ss_cols")
                    if st.button("Сохранить в справочник"):
                        if not new_word or not new_meaning:
                            st.warning("Заполните слово и значение.")
                        else:
                            row = disp_db.query(SemanticShift).filter(
                                SemanticShift.word == new_word,
                                SemanticShift.country == new_country).first()
                            if row is None:
                                row = SemanticShift(word=new_word, country=new_country)
                                disp_db.add(row)
                            row.meaning = new_meaning
                            row.collocations = json.dumps(
                                [c.strip().lower() for c in new_cols.split(",") if c.strip()],
                                ensure_ascii=False)
                            disp_db.commit()
                            st.success("Сохранено. Прогоните P7 заново.")
            finally:
                disp_db.close()

    st.divider()
    st.caption("Сводка по корпусу и выгрузка для качественного анализа (пункт 4.3 ТЗ)")
    sum_db = SessionLocal()
    try:
        corpus_rows = query_engine.corpus_statistics(sum_db)
        if corpus_rows:
            frame = pd.DataFrame(corpus_rows)
            pivot = frame.pivot_table(index="parameter", columns="country",
                                       values="hits", aggfunc="sum", fill_value=0)
            st.bar_chart(pivot)
            st.dataframe(pivot.reset_index(), use_container_width=True)

            from src.query.export import export_workbook_csv, export_workbook_xlsx
            col1, col2 = st.columns(2)
            col1.download_button(
                "Скачать все параметры (CSV)",
                export_workbook_csv(sum_db),
                file_name="matrix_all.csv", mime="text/csv")
            col2.download_button(
                "Скачать сводную книгу (XLSX)",
                export_workbook_xlsx(sum_db),
                file_name="matrix_workbook.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            if st.button("Сравнительный анализ параметра через LLM"):
                from src.analysis.llm import analyze_matrix_parameter_stream
                placeholder = st.empty()
                collected = ""
                for piece in analyze_matrix_parameter_stream(sel_code):
                    collected += piece
                    placeholder.markdown(collected)
        else:
            st.info("Попаданий нет. Сначала прогоните параметры по корпусу.")
    finally:
        sum_db.close()

with tab_dict:
    st.caption("Пункт 5.3 ТЗ: парсинг внешних словарей (слово-значение) в staging с последующим отбором")

    from src.db.models import DictionaryEntry, DictionarySource
    from src.dictionaries.sync import sync_registry, sync_source, sync_all
    from src.dictionaries.validator import approve_entries

    dict_db = SessionLocal()
    try:
        sync_registry(dict_db)
        sources = dict_db.query(DictionarySource).order_by(
            DictionarySource.region, DictionarySource.key).all()

        col_btn_all, col_note = st.columns([1, 3])
        if col_btn_all.button("Обновить все словари"):
            with st.spinner("Парсинг источников..."):
                results = sync_all(dict_db)
            failed = [r for r in results if not r["ok"]]
            st.success(f"Источников обработано: {len(results)}, с ошибками: {len(failed)}")

        src_names = {s.key: f"[{s.region}] {s.title}" for s in sources}
        sel_src = st.selectbox("Источник", list(src_names.keys()),
                               format_func=lambda k: src_names[k])

        cur = next(s for s in sources if s.key == sel_src)
        st.markdown(
            f"**{cur.title}** — [{cur.url}]({cur.url})  \n"
            f"Метод: {cur.extraction}"
            + (" (headless-браузер)" if cur.headless else "")
            + (f"; валидация: {cur.validate}" if cur.validate else "")
            + f"; последний запуск: {cur.last_sync_at or '—'} "
              f"({cur.last_status or 'не выполнялся'})"
        )
        if cur.last_error:
            st.error(f"Ошибка последнего запуска: {cur.last_error}")

        if st.button(f"Обновить данные по словарю «{cur.title}»"):
            with st.spinner("Идет парсинг источника..."):
                res = sync_source(dict_db, sel_src)
            if res["ok"]:
                st.success(
                    f"Загружено статей: {res['inserted']}; "
                    f"статусы: {res['by_status']}"
                )
            else:
                st.error(res["error"])

        pending_rows = dict_db.query(DictionaryEntry).filter_by(
            source_key=sel_src, status="pending").all()
        other_rows = dict_db.query(DictionaryEntry).filter(
            DictionaryEntry.source_key == sel_src,
            DictionaryEntry.status != "pending").all()

        if pending_rows:
            st.write(f"Статей на подтверждении: {len(pending_rows)}")
            df_pending = pd.DataFrame(
                [{"id": r.id, "Термин": r.term, "Определение": r.definition[:160],
                  "Регион": r.region} for r in pending_rows])
            st.dataframe(df_pending, use_container_width=True, height=240)
            if st.button("Подтвердить и перенести в рабочий словарь"):
                moved = approve_entries(dict_db, ids=[r.id for r in pending_rows])
                st.success(f"Перенесено в regional_dictionary: {moved}")
        else:
            st.info("Неподтвержденных статей у этого источника нет.")

        rejected = [r for r in other_rows if r.status.startswith("rejected")]
        if rejected:
            with st.expander(f"Отклонено при валидации: {len(rejected)}"):
                df_rej = pd.DataFrame(
                    [{"Термин": r.term, "Причина": r.note or r.status}
                     for r in rejected[:200]])
                st.dataframe(df_rej, use_container_width=True)

        total_regional = dict_db.query(DictionaryEntry).filter_by(status="approved").count()
        st.caption(f"Всего подтвержденных статей после парсеров: {total_regional}")
    finally:
        dict_db.close()


with tab_llm:
    st.caption("Настройка провайдера и API-ключа для LLM-анализа (пункт 4.3 ТЗ)")

    from src.analysis.settings import PROVIDERS, load_raw, save as save_llm_settings

    current = load_raw()

    provider_names = list(PROVIDERS.keys())
    sel_provider = st.selectbox(
        "Провайдер", provider_names,
        index=provider_names.index(current["provider"]) if current["provider"] in provider_names else 0,
        key="llm_provider",
    )
    defaults = PROVIDERS[sel_provider]

    base_url = st.text_input(
        "Base URL",
        value=current["base_url"] if current["provider"] == sel_provider else defaults["base_url"],
        key="llm_base_url",
    )
    model_name = st.text_input(
        "Модель",
        value=current["model"] if current["provider"] == sel_provider else defaults["model"],
        key="llm_model",
    )

    if current["api_key"]:
        st.markdown(
            f"API-ключ сохранен: `{current['api_key'][:3]}{'*' * 12}`. "
            "Оставьте поле пустым, чтобы не менять его."
        )
    else:
        st.info("API-ключ еще не задан.")

    api_key = st.text_input(
        "API-ключ", type="password", placeholder="Вставьте ключ провайдера",
        key="llm_api_key",
    )

    if st.button("Сохранить настройки LLM"):
        saved = save_llm_settings(
            provider=sel_provider,
            api_key=api_key or None,
            model=model_name or None,
            base_url=base_url or None,
        )
        shown = f"{saved['api_key'][:3]}{'*' * 12}" if saved["api_key"] else "не задан"
        st.success(f"Сохранено: {saved['provider']} | {saved['model']} | ключ: {shown}")
