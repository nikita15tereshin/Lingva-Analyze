import streamlit as st
import sys
import os

# Добавляем корень проекта для правильных импортов
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.nlp.processor import process_text, nlp
from src.parser.reader import extract_and_normalize
from src.db.session import SessionLocal
from src.db.crud import create_document, save_nlp_data_to_db, get_document_index_from_db
from src.analysis.compare import find_unique_lemmas
from src.analysis.matcher import classify_unique_words
from src.analysis.context import get_contexts_for_lemma
from src.analysis.llm import analyze_semantic_context_stream

# Хранилище сессии
if "documents" not in st.session_state:
    st.session_state.documents = {}

if "comparison_results" not in st.session_state:
    st.session_state.comparison_results = None

st.title("Lingva-Analyze MVP 🔍")

if not nlp:
    st.error("❌ Модель spaCy не загружена!")
    st.stop()

# --- СЕКЦИЯ 1: ЗАГРУЗКА ---
st.header("1. Загрузка документа")
# Теперь поддерживаем три формата!
uploaded_file = st.file_uploader("Выберите файл", type=["txt", "pdf", "docx"])

if uploaded_file is not None:
    doc_name = uploaded_file.name
    if st.button(f"Обработать '{doc_name}'"):
        with st.spinner("Извлечение текста и анализ..."):
            # 1. Читаем и нормализуем текст с помощью нашего нового парсера
            raw_text = extract_and_normalize(uploaded_file, doc_name, normalize=True)
            
            if raw_text:
                # 2. Прогоняем через spaCy
                nlp_data = process_text(raw_text)
                
                db = SessionLocal()
                try:
                    # 3. Создаем запись документа в БД
                    db_doc = create_document(db, doc_name)
                    
                    # 4. Сохраняем предложения и токены в реляционные таблицы
                    save_nlp_data_to_db(db, db_doc.id, nlp_data)
                    
                    # 5. Выгружаем готовый индекс из БД для быстрого сравнения
                    index_data = get_document_index_from_db(db, db_doc.id)
                    
                    # В памяти храним только метаданные, тексты теперь живут в БД!
                    st.session_state.documents[doc_name] = {
                        "doc_id": db_doc.id,
                        "index": index_data
                    }
                    st.success(f"Документ '{doc_name}' успешно сохранен в БД и проиндексирован!")
                except Exception as e:
                    st.error(f"Ошибка при сохранении в БД: {e}")
                finally:
                    db.close()

# --- СЕКЦИЯ 2: ПРОСМОТР ИНДЕКСА ---
st.header("2. Загруженные документы")
if not st.session_state.documents:
    st.info("Пока нет загруженных документов.")
else:
    for name, data in st.session_state.documents.items():
        idx_data = data["index"]
        with st.expander(f"📄 {name} (Уникальных лемм: {len(idx_data)})"):
            freq_dict = {lemma: len(coords) for lemma, coords in idx_data.items()}
            sorted_freq = dict(sorted(freq_dict.items(), key=lambda item: item[1], reverse=True))
            st.dataframe(sorted_freq, column_config={"value": "Частота", "_index": "Лемма"})

# --- СЕКЦИЯ 3: СРАВНЕНИЕ И АНАЛИЗ ---
st.header("3. Сравнение текстов")
doc_names = list(st.session_state.documents.keys())

if len(doc_names) >= 2:
    col1, col2 = st.columns(2)
    with col1:
        doc_a_name = st.selectbox("Документ A", doc_names, index=0)
    with col2:
        doc_b_name = st.selectbox("Документ B", doc_names, index=1)
        
    if st.button("Сравнить лексику"):
        if doc_a_name == doc_b_name:
            st.warning("Пожалуйста, выберите разные документы.")
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
                    "classified_b": classified_b
                }
            finally:
                db.close()

    # ЕСЛИ ЕСТЬ РЕЗУЛЬТАТЫ В ПАМЯТИ — ОТРИСОВЫВАЕМ ИХ
    if st.session_state.comparison_results:
        res = st.session_state.comparison_results
        doc_a_name = res["doc_a_name"]
        doc_b_name = res["doc_b_name"]
        classified_a = res["classified_a"]
        classified_b = res["classified_b"]

        st.subheader("Результат анализа:")
        col_res1, col_res2 = st.columns(2)
        
        with col_res1:
            st.write(f"**Анализ '{doc_a_name}':**")
            if classified_a["AT_matches"]:
                formatted_at = [f"**{w['lemma']}** ({w['standard_de']})" for w in classified_a["AT_matches"]]
                st.success(f"🇦🇹 Найдены австрицизмы: {', '.join(formatted_at)}")
            if classified_a["CH_matches"]:
                formatted_ch = [f"**{w['lemma']}** ({w['standard_de']})" for w in classified_a["CH_matches"]]
                st.info(f"🇨🇭 Найдены гельветизмы: {', '.join(formatted_ch)}")
            with st.expander("Остальные уникальные слова (шум)"):
                st.dataframe(classified_a["unknown"], hide_index=True)
            
        with col_res2:
            st.write(f"**Анализ '{doc_b_name}':**")
            if classified_b["AT_matches"]:
                formatted_at = [f"**{w['lemma']}** ({w['standard_de']})" for w in classified_b["AT_matches"]]
                st.success(f"🇦🇹 Найдены австрицизмы: {', '.join(formatted_at)}")
            if classified_b["CH_matches"]:
                formatted_ch = [f"**{w['lemma']}** ({w['standard_de']})" for w in classified_b["CH_matches"]]
                st.info(f"🇨🇭 Найдены гельветизмы: {', '.join(formatted_ch)}")
            with st.expander("Остальные уникальные слова (шум)"):
                st.dataframe(classified_b["unknown"], hide_index=True)

      # --- СЕКЦИЯ 4: LLM АНАЛИЗ ---
        st.divider()
        st.subheader("🧠 Семантический анализ (Kimi)")
        
        all_matches = []
        for w in classified_a["AT_matches"]: all_matches.append({"lemma": w["lemma"], "region": "AT", "doc": doc_a_name})
        for w in classified_a["CH_matches"]: all_matches.append({"lemma": w["lemma"], "region": "CH", "doc": doc_a_name})
        for w in classified_b["AT_matches"]: all_matches.append({"lemma": w["lemma"], "region": "AT", "doc": doc_b_name})
        for w in classified_b["CH_matches"]: all_matches.append({"lemma": w["lemma"], "region": "CH", "doc": doc_b_name})
        
        if all_matches:
            options = [f"{m['lemma']} ({m['region']}) — документ: {m['doc']}" for m in all_matches]
            selected_option = st.selectbox("Выберите слово для глубокого разбора:", options, key="llm_select_word")
            
            if st.button("🚀 Отправить в нейросеть (Stream)"):
                match_info = next(m for m in all_matches if f"{m['lemma']} ({m['region']}) — документ: {m['doc']}" == selected_option)
                lemma = match_info["lemma"]
                region = match_info["region"]
                doc_name = match_info["doc"]
                
                doc_id = st.session_state.documents[doc_name]["doc_id"]
                
                db = SessionLocal()
                try:
                    contexts = get_contexts_for_lemma(db, lemma, doc_id)
                    
                    if contexts:
                        full_context = contexts[0]["full_context"]
                        st.info(f"**Найденный контекст в БД:** {full_context}")
                        
                        st.success("Ответ Kimi (поток в реальном времени):")
                        # Импортируем наш новый стрим-метод
                        from src.analysis.llm import analyze_semantic_context_stream
                        
                        # Streamlit сам умеет красиво выводить генератор чанков по мере их поступления!
                        st.write_stream(analyze_semantic_context_stream(lemma, full_context, region))
                    else:
                        st.error("❌ Не удалось найти предложения с этим словом в базе данных.")
                finally:
                    db.close()
        else:
            st.info("Регионализмы не найдены, анализ LLM недоступен.")