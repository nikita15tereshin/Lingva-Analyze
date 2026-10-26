import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Значения по умолчанию для тестов; реальные значения задаются через переменные окружения.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "test-key-not-real")

# Если spaCy не установлен (например, в легковесном CI), подменяем модуль заглушкой,
# чтобы модули проекта оставались импортируемыми.
try:
    import spacy  # noqa: F401
except ImportError:
    import types

    _spacy_stub = types.ModuleType("spacy")

    def _load_stub(name):
        raise OSError(f"spaCy model {name} is not available in the test environment")

    _spacy_stub.load = _load_stub
    sys.modules["spacy"] = _spacy_stub
