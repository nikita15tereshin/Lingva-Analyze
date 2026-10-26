"""Настройки LLM-провайдера: реестр провайдеров и хранилище.

Значения по умолчанию берутся из переменных окружения (LLM_API_KEY,
LLM_BASE_URL, LLM_MODEL). Пользовательские настройки хранятся в JSON-файле
(путь: env LINGVA_LLM_SETTINGS_FILE или data/llm_settings.json). API-ключ
наружу не отдается: только маска и признак наличия.
"""

import json
import os
import threading

PROVIDERS = {
    "TokenRouter": {
        "base_url": "https://api.tokenrouter.com/v1",
        "model": "moonshotai/kimi-k3-free",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "Anthropic (Claude)": {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct",
    },
    "Local (Ollama)": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
    },
    "Custom": {
        "base_url": "",
        "model": "",
    },
}

DEFAULT_PROVIDER = "TokenRouter"
MASK = "*" * 12


def _settings_path() -> str:
    return os.getenv(
        "LINGVA_LLM_SETTINGS_FILE",
        os.path.join("data", "llm_settings.json"),
    )


_lock = threading.Lock()


def _env_defaults() -> dict:
    base = PROVIDERS[DEFAULT_PROVIDER]
    return {
        "provider": DEFAULT_PROVIDER,
        "base_url": os.getenv("LLM_BASE_URL") or base["base_url"],
        "model": os.getenv("LLM_MODEL") or base["model"],
        "api_key": os.getenv("LLM_API_KEY") or "",
    }


def load_raw() -> dict:
    """Полные настройки, включая ключ. Только для внутреннего использования."""
    settings = _env_defaults()
    path = _settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            for field in ("provider", "base_url", "model", "api_key"):
                if stored.get(field):
                    settings[field] = stored[field]
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save(provider=None, api_key=None, model=None, base_url=None) -> dict:
    """Сохраняет переданные поля; пустой или замаскированный ключ ничего не перезаписывает."""
    with _lock:
        current = load_raw()
        if provider and provider in PROVIDERS:
            current["provider"] = provider
            defaults = PROVIDERS[provider]
            current["base_url"] = base_url or defaults["base_url"]
            current["model"] = model or defaults["model"]
        else:
            if base_url:
                current["base_url"] = base_url
            if model:
                current["model"] = model
        if api_key and api_key.strip() and not set(api_key.strip()) <= {"*"}:
            current["api_key"] = api_key.strip()
        path = _settings_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return current


def public_view() -> dict:
    """Настройки для фронтенда: вместо ключа - маска и признак наличия."""
    raw = load_raw()
    key = raw.get("api_key") or ""
    return {
        "provider": raw["provider"],
        "base_url": raw["base_url"],
        "model": raw["model"],
        "providers": sorted(PROVIDERS.keys()),
        "has_key": bool(key),
        "key_mask": (key[:3] + MASK) if key else "",
    }
