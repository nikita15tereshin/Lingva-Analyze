import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import streamlit as st
import pandas as pd

from src.nlp.processor import process_text, nlp
from src.parser.reader import extract_and_normalize
from src.db.session import SessionLocal
from src.db.crud import create_document, save_nlp_data_to_db, get_document_index_from_db
from src.analysis.compare import find_unique_lemmas
from src.analysis.matcher import classify_unique_words
from src.analysis.context import get_contexts_for_lemma
from src.analysis.llm import analyze_semantic_context_stream

st.set_page_config(page_title="Lingva-Analyze", layout="wide")

CUSTOM_CSS = """
<style>
/* Общая типографика */
html [data-testid="stAppViewContainer"] {
    font-family: "Source Sans 3", "Segoe UI", sans-serif;
}
header[data-testid="column-header"], .col-header {
    font-weight: 600;
}
/* Шапка приложения */
.la-page-title {
    font-size: 1.7rem;
    font-weight: 700;
    color: #1b2a4a;
    border-bottom: 3px solid #1b2a4a;
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}
.la-section-caption {
    color: #5c6b7a;
    font-size: 0.9rem;
    margin-bottom: 1rem;
}
/* Карточки секций */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 8px;
}
/* Таблицы частот */
div[data-testid="stDataFrame"] {
    border: 1px solid #d9dee5;
    border-radius: 6px;
}
/* Подсветка найденного слова в контексте */
.la-context {
    background: #f4f6f9;
    border-left: 4px solid #1b2a4a;
    border-radius: 4px;
    padding: 0.8rem 1rem;
    line-height: 1.6;
}
.la-mark {
    background: #fff3bf;
    padding: 0 0.25rem;
    border-radius: 3px;
    font-weight: 700;
}
/* Статус-блок обработки */
.la-status-ok {
    color: #1e6f43;
    font-weight: 600;
}
.la-status-err {
    color: #b3261e;
    font-weight: 600;
}
</style>
"""

if "documents" not in st.session_state:
    st.session_state.documents = {}

if "comparison_results" not in st.session_state:
    st.session_state.comparison_results = None


def highlight_word(sentence: str, word: str) -> str:
    """Возвращает предложение с HTML-подсветкой найденной формы слова."""
    if not sentence or not word:
        return sentence or ""
    escaped = sentence.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    highlighted = escaped.replace(word, f'<span class="la-mark">{word}</span>')
    return highlighted


st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
st.markdown('<div class="la-page-title">Lingva-Analyze</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="la-section-caption">'
    "Сравнительный анализ региональных вариантов немецкого языка "
    "(Германия, Австрия, Швейцария) по корпусу документов.</div>",
    unsafe_allow_html=True,
)

if not nlp:
    st.error(
        "Модель spaCy не загружена. Установите её командой: "
        "`python -m spacy download de_core_news_sm` и перезапустите приложение."
    )
    st.stop()

with st.sidebar:
    st.header("Навигация")
    st.markdown(
        "1. Загрузите документ (TXT, PDF или DOCX).\n"
        "2. Проверьте лексический индекс.\n"
        "3. Сравните два документа.\n"
        "4. Отправьте найденный регионализм на семантический разбор."
    )
    st.divider()
    docs_in_db = len(st.session_state.documents)
    st.metric("Документов в сессии", docs_in_db)

# --- Раздел 1: загрузка документа ---
st.header("1. Загрузка документа")
uploaded_file = st.file_uploader("Файл документа", type=["txt", "pdf", "docx"])

if uploaded_file is not None:
    doc_name = uploaded_file.name
    if st.button(f"Обработать файл «{doc_name}»", use_container_width=True):
        with st.spinner("Извлечение текста, лемматизация и индексация..."):
            raw_text = extract_and_normalize(uploaded_file, doc_name, normalize=True)

            if raw_text:
                nlp_data = process_text(raw_text)

                db = SessionLocal()
                try:
                    db_doc = create_document(db, doc_name)
                    save_nlp_data_to_db(db, db_doc.id, nlp_data)
                    index_data = get_document_index_from_db(db, db_doc.id)

                    st.session_state.documents[doc_name] = {
                        "doc_id": db_doc.id,
                        "index": index_data,
                    }
                    st.success(
                        f"Документ «{doc_name}» сохранен в БД, "
                        f"проиндексировано лемм: {len(index_data)}."
                    )
                except Exception as e:
                    st.error(f"Ошибка при сохранении в БД: {e}")
                finally:
                    db.close()
            else:
                st.warning("В файле не удалось обнаружить текст.")

# --- Раздел 2: просмотр индекса ---
st.header("2. Загруженные документы")
if not st.session_state.documents:
    st.info("Загруженных документов пока нет.")
else:
    for name, data in st.session_state.documents.items():
        idx_data = data["index"]
        with st.expander(f"{name} (ID в БД: {data['doc_id']}, уникальных лемм: {len(idx_data)})"):
            freq_df = pd.DataFrame(
                {"Лемма": list(idx_data.keys()), "Частота": [len(c) for c in idx_data.values()]}
            ).sort_values("Частота", ascending=False)
            st.dataframe(freq_df, hide_index=True, use_container_width=True)

# --- Раздел 3: сравнение и анализ ---
st.header("3. Сравнение текстов")
doc_names = list(st.session_state.documents.keys())

if len(doc_names) >= 2:
    col1, col2 = st.columns(2)
    with col1:
        doc_a_name = st.selectbox("Документ A", doc_names, index=0)
    with col2:
        doc_b_name = st.selectbox("Документ B", doc_names, index=1 if len(doc_names) > 1 else 0)

    if st.button("Сравнить лексику", type="primary"):
        if doc_a_name == doc_b_name:
            st.warning("Выберите два разных документа.")
        else:
            idx_a = st.session_state.documents[doc_a_name]["index"]
            idx_b = st.session_state.documents[doc_b_name]["index"]

            result = find_unique_lemmas(idx_a, idx_b)

            db = SessionLocal()
            try:
                classified_a = classify_unique_words(db, result["unique_A"])
                classified_b = classify_unique_words(db, result["unique_B"])

                st.session_state.comparison_results = {
                    "doc_a_name": doc_a_name,
                    "doc_b_name": doc_b_name,
                    "classified_a": classified_a,
                    "classified_b": classified_b,
                }
            finally:
                db.close()

    if st.session_state.comparison_results:
        res = st.session_state.comparison_results
        doc_a_name = res["doc_a_name"]
        doc_b_name = res["doc_b_name"]
        classified_a = res["classified_a"]
        classified_b = res["classified_b"]

        st.subheader("Результат сравнения")

        stat1, stat2, stat3, stat4 = st.columns(4)
        stat1.metric(f"Австрицизмы, документ A", len(classified_a["AT_matches"]))
        stat2.metric(f"Гельветизмы, документ A", len(classified_a["CH_matches"]))
        stat3.metric(f"Австрицизмы, документ B", len(classified_b["AT_matches"]))
        stat4.metric(f"Гельветизмы, документ B", len(classified_b["CH_matches"]))

        def render_side(classified: dict, doc_label: str):
            at_rows = pd.DataFrame(
                [{"Лемма": w["lemma"], "Нейтральный вариант": w["standard_de"]}
                 for w in classified["AT_matches"]]
            )
            ch_rows = pd.DataFrame(
                [{"Лемма": w["lemma"], "Нейтральный вариант": w["standard_de"]}
                 for w in classified["CH_matches"]]
            )
            unknown_rows = pd.DataFrame({"Лемма": classified["unknown"]})

            st.markdown(f"**{doc_label}**")

            st.caption("Австрицизмы")
            if at_rows.empty:
                st.write("Не найдено.")
            else:
                st.dataframe(at_rows, hide_index=True, use_container_width=True)

            st.caption("Гельветизмы")
            if ch_rows.empty:
                st.write("Не найдено.")
            else:
                st.dataframe(ch_rows, hide_index=True, use_container_width=True)

            with st.expander(f"Уникальные слова вне словарей ({len(unknown_rows)})"):
                if unknown_rows.empty:
                    st.write("Нет данных.")
                else:
                    st.dataframe(unknown_rows, hide_index=True, use_container_width=True)

        col_res1, col_res2 = st.columns(2)
        with col_res1:
            render_side(classified_a, doc_a_name)
        with col_res2:
            render_side(classified_b, doc_b_name)

        # --- Раздел 4: семантический анализ через LLM ---
        st.divider()
        st.subheader("Семантический анализ найденных регионализмов")

        all_matches = []
        for w in classified_a["AT_matches"]:
            all_matches.append({"lemma": w["lemma"], "region": "AT", "doc": doc_a_name})
        for w in classified_a["CH_matches"]:
            all_matches.append({"lemma": w["lemma"], "region": "CH", "doc": doc_a_name})
        for w in classified_b["AT_matches"]:
            all_matches.append({"lemma": w["lemma"], "region": "AT", "doc": doc_b_name})
        for w in classified_b["CH_matches"]:
            all_matches.append({"lemma": w["lemma"], "region": "CH", "doc": doc_b_name})

        if all_matches:
            options = [f"{m['lemma']} ({m['region']}) — {m['doc']}" for m in all_matches]
            selected_option = st.selectbox("Слово для разбора:", options, key="llm_select_word")

            if st.button("Отправить запрос в LLM"):
                match_info = all_matches[options.index(selected_option)]
                lemma = match_info["lemma"]
                region = match_info["region"]
                doc_name = match_info["doc"]

                doc_id = st.session_state.documents[doc_name]["doc_id"]

                db = SessionLocal()
                try:
                    contexts = get_contexts_for_lemma(db, lemma, doc_id)

                    if contexts:
                        full_context = contexts[0]["full_context"]
                        target_sentence = contexts[0]["target_sentence"]

                        st.markdown(
                            f'<div class="la-context">{highlight_word(target_sentence, lemma)}'
                            f"<br><small>Полный контекст: {highlight_word(full_context, lemma)}</small></div>",
                            unsafe_allow_html=True,
                        )

                        st.write_stream(analyze_semantic_context_stream(lemma, full_context, region))
                    else:
                        st.error("В базе данных не найдено предложений с этим словом.")
                finally:
                    db.close()
        else:
            st.info("Регионализмы не найдены, семантический анализ недоступен.")
else:
    st.caption("Для сравнения необходимо загрузить минимум два документа.")