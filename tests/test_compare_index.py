from src.analysis.compare import find_unique_lemmas, print_comparison_table
from src.index.indexer import build_index, save_index_to_json, load_index_from_json


SENTENCES = [
    {
        "sent_id": 0,
        "tokens": [
            {"word": "Die", "lemma": "die", "pos": "DET"},
            {"word": "Bundeswehr", "lemma": "Bundeswehr", "pos": "NOUN"},
            {"word": ".", "lemma": ".", "pos": "PUNCT"},
        ],
    },
    {
        "sent_id": 1,
        "tokens": [
            {"word": "Ein", "lemma": "ein", "pos": "DET"},
            {"word": "Soldat", "lemma": "Soldat", "pos": "NOUN"},
            {"word": ".", "lemma": ".", "pos": "PUNCT"},
        ],
    },
]


def test_build_index_skips_punctuation():
    index = build_index(doc_id=1, sentences=SENTENCES)
    assert set(index.keys()) == {"die", "Bundeswehr", "ein", "Soldat"}
    assert index["Bundeswehr"] == [(0, 1)]


def test_find_unique_lemmas():
    index_a = {"Bundeswehr": [(0, 0)], "der": [(0, 1)]}
    index_b = {"Bundesheer": [(0, 0)], "der": [(0, 1)]}
    result = find_unique_lemmas(index_a, index_b)
    assert result["unique_A"] == ["Bundeswehr"]
    assert result["unique_B"] == ["Bundesheer"]


def test_print_comparison_table(capsys):
    result = {"unique_A": ["Marille"], "unique_B": ["Billett"]}
    print_comparison_table(result, "AT", "CH")
    out = capsys.readouterr().out
    assert "Marille" in out and "Billett" in out


def test_save_and_load_index(tmp_path):
    index = build_index(doc_id=1, sentences=SENTENCES)
    path = str(tmp_path / "index.json")
    save_index_to_json(index, path)
    loaded = load_index_from_json(path)
    # JSON хранит ключи строками, координаты возвращаются списками
    assert loaded["Bundeswehr"] == [[0, 1]]
