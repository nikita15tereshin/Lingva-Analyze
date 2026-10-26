import io
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text as sa_text

from src.parser.reader import extract_and_normalize
from src.nlp.processor import process_text
from src.db.session import SessionLocal, engine
from src.db.models import Base, Document
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

tab_lexicon, tab_kwic, tab_matrix, tab_dict = st.tabs(
    ["Лексический индекс", "KWIC-конкорданс", "Матрица параметров", "Словари"]
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
    result = classify_unique_words(db if False else SessionLocal(), unique_words)
    st.write("Австрицизмы:", [w["lemma"] for w in result["AT_matches"]][:30])
    st.write("Гельветизмы:", [w["lemma"] for w in result["CH_matches"]][:30])

with tab_kwic:
    lemma_query = st.text_input("Лемма для поиска контекстов", value="Bundeswehr")
    if lemma_query and st.button("Показать KWIC"):
        contexts = get_contexts_for_lemma(SessionLocal(), lemma_query, active_doc_id)
        if not contexts:
            st.write("Ничего не найдено в текущем документе.")
        for ctx in contexts[:20]:
            st.markdown(f"**{ctx['word_form']}** (позиция {ctx['position']})")
            st.write(ctx["target_sentence"])

            if st.button("Объяснить через LLM", key=f"llm_{ctx['position']}_{hash(ctx['target_sentence'])}"):
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
        st.success(f"Создано параметров: {counts['parameters']}, пар замен: {counts['lexical_pairs']}")

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
