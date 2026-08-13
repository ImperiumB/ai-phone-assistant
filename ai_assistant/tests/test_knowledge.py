import json
import numpy as np
import pytest

from ai_assistant.service.knowledge import (
    KnowledgeBase,
    KnowledgeRecord,
    load_knowledge_base,
)


class FakeEmbedder:
    """Отдаёт заранее заданный вектор для каждой известной строки.

    Неизвестные строки получают вектор, ортогональный всем остальным,
    поэтому близость с ними равна нулю.
    """

    def __init__(self, mapping):
        self._mapping = mapping

    def encode(self, texts):
        vectors = []
        for text in texts:
            # KnowledgeBase добавляет префиксы search_query:/search_document: — снимаем их,
            # чтобы искать по исходной фразе.
            clean = text.split(": ", 1)[-1] if text.startswith("search_") else text
            vector = self._mapping.get(clean, [0.0, 0.0, 1.0])
            array = np.array(vector, dtype=np.float32)
            vectors.append(array / np.linalg.norm(array))
        return np.vstack(vectors)


def make_record(record_id, question):
    return KnowledgeRecord(
        id=record_id,
        question=question,
        clarifying_question="Правильно я понял, что вас интересует ремонт?",
        positive_answers=["да", "верно"],
        negative_answers=["нет", "не то"],
        positive_reply="Соединяю с отделом продаж",
        scenario="redirect_sales",
        equipment_type="Стиральные машины",
    )


@pytest.fixture
def base():
    embedder = FakeEmbedder({
        "стиральная машина не отжимает": [1.0, 0.0, 0.0],
        "не работает холодильник": [0.0, 1.0, 0.0],
        "стиралка не крутит бельё": [0.97, 0.24, 0.0],
        "во сколько вы открываетесь": [0.0, 0.0, 1.0],
    })
    records = [
        make_record(1, "стиральная машина не отжимает"),
        make_record(2, "не работает холодильник"),
    ]
    return KnowledgeBase(records, embedder, threshold=0.75)


def test_finds_record_close_in_meaning(base):
    found = base.search("стиралка не крутит бельё")
    assert found is not None
    record, score = found
    assert record.id == 1
    assert score > 0.75


def test_returns_none_when_nothing_is_close_enough(base):
    assert base.search("во сколько вы открываетесь") is None


def test_exact_question_matches_itself(base):
    found = base.search("не работает холодильник")
    assert found is not None
    assert found[0].id == 2


def test_added_question_gets_next_id_and_empty_clarifying(base):
    record = base.add("во сколько вы открываетесь")
    assert record.id == 3
    assert record.question == "во сколько вы открываетесь"
    assert record.clarifying_question == ""


def test_added_question_is_saved_to_disk(base, tmp_path):
    base.add("во сколько вы открываетесь")
    target = tmp_path / "kb.json"
    base.save(str(target))
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload) == 3
    assert payload[2]["question"] == "во сколько вы открываетесь"


def test_load_reads_all_records_from_file(tmp_path):
    source = [
        {
            "id": 7,
            "question": "течёт посудомойка",
            "clarifying_question": "Речь о посудомоечной машине?",
            "positive_answers": ["да"],
            "negative_answers": ["нет"],
            "positive_reply": "Соединяю",
            "scenario": "redirect_sales",
            "equipment_type": "Посудомоечные машины",
        }
    ]
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    embedder = FakeEmbedder({"течёт посудомойка": [1.0, 0.0, 0.0]})
    base = load_knowledge_base(str(path), embedder, threshold=0.75)
    found = base.search("течёт посудомойка")
    assert found is not None
    assert found[0].id == 7
    assert found[0].equipment_type == "Посудомоечные машины"
