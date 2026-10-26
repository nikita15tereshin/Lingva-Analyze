import io

from fastapi.testclient import TestClient

from src.api import main as api_main


class FakeDoc:
    id = 42


def _patch_pipeline(monkeypatch):
    monkeypatch.setattr(api_main, "extract_and_normalize", lambda *a, **k: "Die Bundeswehr übt.")
    monkeypatch.setattr(api_main, "create_document", lambda db, filename: FakeDoc())
    monkeypatch.setattr(
        api_main, "process_text",
        lambda text: {"sentences": [{"sent_id": 0, "tokens": [
            {"word": "Die", "lemma": "die", "pos": "DET"},
            {"word": "Bundeswehr", "lemma": "Bundeswehr", "pos": "NOUN"},
        ]}]},
    )
    monkeypatch.setattr(api_main, "save_nlp_data_to_db", lambda db, doc_id, nlp_data: None)
    monkeypatch.setattr(
        api_main, "get_document_index_from_db",
        lambda db, doc_id: {"die": [(0, 0)], "Bundeswehr": [(0, 1)]},
    )


def test_upload_status_and_index(monkeypatch):
    _patch_pipeline(monkeypatch)
    client = TestClient(api_main.app)

    resp = client.post(
        "/upload",
        files={"file": ("test.txt", io.BytesIO("Die Bundeswehr übt.".encode()), "text/plain")},
        data={"country": "DE", "doc_type": "01"},
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    status_resp = client.get(f"/status/{task_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "готово"

    index_resp = client.get("/index/42")
    assert index_resp.status_code == 200
    body = index_resp.json()
    assert body["unique_words_count"] == 2
    assert "Bundeswehr" in body["index_data"]


def test_index_not_found(monkeypatch):
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(api_main, "get_document_index_from_db", lambda db, doc_id: {})
    client = TestClient(api_main.app)

    resp = client.get("/index/999")
    assert resp.status_code == 200
    assert "error" in resp.json()


def test_status_unknown_task():
    client = TestClient(api_main.app)
    resp = client.get("/status/nonexistent-task")
    assert resp.json()["status"] == "Задача не найдена"
