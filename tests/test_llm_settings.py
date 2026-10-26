"""Тесты настроек LLM-провайдера и соответствующих эндпоинтов API."""

import json
import os

import pytest


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "llm_settings.json"
    monkeypatch.setenv("LINGVA_LLM_SETTINGS_FILE", str(path))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    return path


def test_save_and_public_view(settings_file):
    from src.analysis.settings import save, public_view, load_raw

    save(provider="OpenAI", api_key="sk-test-1234567890")
    raw = load_raw()
    assert raw["provider"] == "OpenAI"
    assert raw["api_key"] == "sk-test-1234567890"
    assert raw["base_url"] == "https://api.openai.com/v1"

    view = public_view()
    assert view["has_key"] is True
    assert view["key_mask"].startswith("sk-")
    assert "*" in view["key_mask"]
    assert "sk-test-1234567890" not in json.dumps(view)


def test_masked_key_does_not_overwrite(settings_file):
    from src.analysis.settings import save, load_raw

    save(provider="DeepSeek", api_key="secret-key")
    save(api_key="************")  # маска из UI не должна затирать реальный ключ
    save(api_key="   ")
    assert load_raw()["api_key"] == "secret-key"


def test_provider_switch_updates_defaults(settings_file):
    from src.analysis.settings import save, load_raw

    save(provider="Groq", api_key="k")
    assert load_raw()["model"] == "llama-3.3-70b-versatile"
    save(model="custom-model")
    assert load_raw()["model"] == "custom-model"


def test_llm_module_uses_settings(settings_file, monkeypatch):
    """Без сохраненного ключа стримеры выдают подсказку про вкладку LLM."""
    from src.analysis import llm

    chunks = list(llm.analyze_semantic_context_stream("Marille", "Die Marille reift.", "AT"))
    assert any("вкладку LLM" in c for c in chunks)

    save_chunks = list(llm.analyze_matrix_parameter_stream("P5"))
    assert any("вкладку LLM" in c for c in save_chunks)


def test_api_llm_settings_endpoints(settings_file):
    from fastapi.testclient import TestClient
    from src.api.main import app

    client = TestClient(app)

    resp = client.get("/llm/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data and "OpenAI" in data["providers"]
    assert "api_key" not in data

    resp = client.post("/llm/settings", json={"provider": "OpenAI", "api_key": "sk-abcdef123456"})
    assert resp.status_code == 200
    assert resp.json()["provider"] == "OpenAI"
    assert resp.json()["has_key"] is True

    resp = client.post("/llm/settings", json={"provider": "NoSuchProvider"})
    assert resp.status_code == 400
