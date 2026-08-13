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

    Требует префиксы search_query: или search_document: для защиты от регрессии.
    Неизвестные строки получают вектор, ортогональный всем остальным,
    поэтому близость с ними равна нулю.
    """

    def __init__(self, mapping):
        self._mapping = mapping

    def encode(self, texts):
        vectors = []
        for text in texts:
            # KnowledgeBase обязан добавлять префиксы search_query:/search_document:
            if text.startswith("search_query: "):
                clean = text[len("search_query: "):]
            elif text.startswith("search_document: "):
                clean = text[len("search_document: "):]
            else:
                raise AssertionError(
                    f"KnowledgeBase должен добавлять префикс 'search_query: ' или 'search_document: ', "
                    f"получен текст без префикса: {text!r}"
                )
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


def test_best_match_returns_the_closest_record_even_below_threshold(base):
    """Item 6 финального ревью: best_match() нужен для логирования меры
    близости даже на промахе — в отличие от search(), он не режет по порогу."""
    match = base.best_match("во сколько вы открываетесь")
    assert match is not None
    record, score = match
    assert score < base.threshold


def test_threshold_property_exposes_the_configured_value(base):
    assert base.threshold == pytest.approx(0.75)


def test_exact_question_matches_itself(base):
    found = base.search("не работает холодильник")
    assert found is not None
    assert found[0].id == 2


def test_added_record_without_clarifying_question_is_excluded_from_search(base):
    """Item 7 финального ревью: неопознанные реплики не должны отравлять
    поиск. Раньше добавленная запись сразу переиндексировалась и участвовала
    в поиске для следующих реплик — дословный повтор той же фразы (например,
    та же ошибка распознавания на втором движке) "находил" бы её вместо
    честного промаха, хотя ветка обработки на пустой уточняющий вопрос
    отвечает мгновенным переводом без уточнения."""
    base.add("во сколько вы открываетесь")
    assert base.search("во сколько вы открываетесь") is None


def test_best_match_also_excludes_records_without_a_clarifying_question(base):
    base.add("во сколько вы открываетесь")
    match = base.best_match("во сколько вы открываетесь")
    assert match is None or match[0].question != "во сколько вы открываетесь"


def test_added_record_is_still_persisted_for_manual_curation(base, tmp_path):
    """Спецификация просит дописывать неопознанный вопрос в файл — для
    последующей ручной разметки, а не подмешивать в живой поиск. save()
    обязан сохранить запись, даже раз она не участвует в поиске."""
    base.add("во сколько вы открываетесь")
    target = tmp_path / "kb.json"
    base.save(str(target))
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert any(item["question"] == "во сколько вы открываетесь" for item in payload)


def test_loading_a_base_with_a_pre_existing_blank_record_excludes_it_too(tmp_path):
    """Не только записи, добавленные через add() в этом же процессе — запись
    с уже пустым уточняющим вопросом в самом JSON (например, из прошлого
    прогона до этой правки) тоже не должна попадать в поиск после
    перезагрузки базы."""
    source = [
        {
            "id": 1,
            "question": "стиральная машина не отжимает",
            "clarifying_question": "",
            "positive_answers": [],
            "negative_answers": [],
            "positive_reply": "",
            "scenario": "",
            "equipment_type": "",
        }
    ]
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    embedder = FakeEmbedder({"стиральная машина не отжимает": [1.0, 0.0, 0.0]})
    base = load_knowledge_base(str(path), embedder, threshold=0.75)
    assert base.search("стиральная машина не отжимает") is None


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


class RecordingEmbedder:
    """Эмбеддер, запоминающий все полученные строки для проверки префиксов."""

    def __init__(self, mapping):
        self._mapping = mapping
        self.received_texts = []

    def encode(self, texts):
        vectors = []
        for text in texts:
            self.received_texts.append(text)
            # Требуем префикс
            if text.startswith("search_query: "):
                clean = text[len("search_query: "):]
            elif text.startswith("search_document: "):
                clean = text[len("search_document: "):]
            else:
                raise AssertionError(f"Missing prefix: {text!r}")
            vector = self._mapping.get(clean, [0.0, 0.0, 1.0])
            array = np.array(vector, dtype=np.float32)
            vectors.append(array / np.linalg.norm(array))
        return np.vstack(vectors)


def test_knowledge_base_adds_search_prefixes():
    """Проверяет, что KnowledgeBase добавляет префиксы search_query: и search_document:."""
    embedder = RecordingEmbedder({
        "стиральная машина не отжимает": [1.0, 0.0, 0.0],
        "не работает холодильник": [0.0, 1.0, 0.0],
    })
    records = [
        make_record(1, "стиральная машина не отжимает"),
        make_record(2, "не работает холодильник"),
    ]
    base = KnowledgeBase(records, embedder, threshold=0.75)

    # Проверяем, что при построении базы все документы получили префикс search_document:
    for text in embedder.received_texts:
        assert text.startswith("search_document: "), f"Документ должен иметь префикс: {text!r}"

    # Очищаем список для проверки search
    embedder.received_texts = []

    # Проверяем, что при поиске запрос получает префикс search_query:
    base.search("стиральная машина не отжимает")
    assert any(t.startswith("search_query: ") for t in embedder.received_texts), \
        f"Запрос должен иметь префикс search_query:, получено: {embedder.received_texts}"
