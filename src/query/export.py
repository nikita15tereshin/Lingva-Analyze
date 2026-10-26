"""Экспорт результатов матрицы для дальнейшего анализа (пункты 4.1, 4.2, 4.3 ТЗ).

CSV — плоский выгрузочный файл по одному параметру.
XLSX — сводная книга по всем прогнанным параметрам сразу: лист со
статистикой по странам, лист с разбивкой по маркерам, листы контекстов.
Файл передается в LLM для качественной части (4.3).
"""

import io

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Hit, QueryParameter, Sentence
from src.query import engine


def parameters_with_hits(db: Session) -> list[str]:
    """Коды параметров, по которым есть хотя бы один hit."""
    rows = (
        db.query(QueryParameter.code)
        .join(Hit, Hit.parameter_id == QueryParameter.id)
        .group_by(QueryParameter.code)
        .order_by(QueryParameter.code)
        .all()
    )
    return [row[0] for row in rows]


def export_parameter_csv(db: Session, parameter_code: str) -> bytes:
    """CSV: строки контекста (документ, код, страна, предложение, маркер, форма)."""
    rows = engine.hits_with_context(db, parameter_code, limit=100000)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["document", "code", "country",
                                      "sentence", "marker", "word_form"])
    return frame.to_csv(index=False).encode("utf-8-sig")


def export_workbook_csv(db: Session) -> bytes:
    """Один CSV по всем параметрам с колонкой parameter.

    Включает и документные hit'ы без предложения (частотный срез), иначе
    такие параметры не попали бы ни в одну выгрузку.
    """
    from src.db.models import Document as _Doc

    frames = []
    for code in parameters_with_hits(db):
        rows = (
            db.query(Hit, Sentence.text, _Doc.filename, _Doc.external_code, _Doc.country)
            .join(_Doc, Hit.document_id == _Doc.id)
            .outerjoin(Sentence, Hit.sentence_id == Sentence.id)
            .join(QueryParameter, Hit.parameter_id == QueryParameter.id)
            .filter(QueryParameter.code == code)
            .order_by(Hit.id)
            .limit(100000)
            .all()
        )
        part = pd.DataFrame([
            {
                "parameter": code,
                "document": filename,
                "code": external_code,
                "country": country,
                "sentence": text or "",
                "marker": hit.matched_marker,
                "word_form": hit.word_form,
            }
            for hit, text, filename, external_code, country in rows
        ])
        if not part.empty:
            frames.append(part)
    if not frames:
        return b""
    columns = ["parameter", "document", "code", "country",
               "sentence", "marker", "word_form"]
    merged = pd.concat(frames, ignore_index=True)[columns]
    return merged.to_csv(index=False).encode("utf-8-sig")


def _summary_rows(db: Session) -> list[dict]:
    rows = (
        db.query(QueryParameter.code, QueryParameter.name,
                 QueryParameter.query_type, func.count(Hit.id))
        .outerjoin(Hit, Hit.parameter_id == QueryParameter.id)
        .group_by(QueryParameter.code, QueryParameter.name, QueryParameter.query_type)
        .order_by(QueryParameter.code)
        .all()
    )
    return [{"Параметр": code, "Название": name, "Тип": qtype, "Попаданий": count}
            for code, name, qtype, count in rows]


def export_workbook_xlsx(db: Session) -> bytes:
    """Сводная книга XLSX: Сводка + по каждому параметру статистика и контексты."""
    buffer = io.BytesIO()
    codes = parameters_with_hits(db)

    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        pd.DataFrame(_summary_rows(db)).to_excel(
            writer, sheet_name="Сводка", index=False)

        if not codes:
            pd.DataFrame(columns=["Параметр", "Попаданий"]).to_excel(
                writer, sheet_name="Нет данных", index=False)
        for code in codes:
            by_country = pd.DataFrame(engine.statistics_by_country(db, code))
            by_marker = pd.DataFrame(engine.statistics_by_marker(db, code))
            contexts = pd.DataFrame(
                engine.hits_with_context(db, code, limit=5000))
            safe = code.replace("/", "_")[:28]
            if not by_country.empty:
                by_country.to_excel(writer, sheet_name=f"{safe}_страны",
                                    index=False)
            if not by_marker.empty:
                by_marker.to_excel(writer, sheet_name=f"{safe}_маркеры",
                                   index=False)
            if not contexts.empty:
                contexts.to_excel(writer, sheet_name=f"{safe}_контексты",
                                  index=False)

    return buffer.getvalue()
