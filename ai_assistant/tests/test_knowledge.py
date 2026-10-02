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


def test_variants_lead_to_their_own_record():
    """Синоним обязан находить свою запись наравне с основной формулировкой."""
    embedder = FakeEmbedder({
        "стиральная машина не отжимает": [1.0, 0.0, 0.0],
        "стиралка машинка сломалась": [1.0, 0.0, 0.0],
        "не морозит холодильник": [0.0, 1.0, 0.0],
    })
    records = [
        KnowledgeRecord(
            id=1,
            question="стиральная машина не отжимает",
            question_variants=["стиралка машинка сломалась"],
            clarifying_question="Речь о стиральной машине?",
        ),
        KnowledgeRecord(
            id=2,
            question="не морозит холодильник",
            clarifying_question="Речь о холодильнике?",
        ),
    ]
    base = KnowledgeBase(records, embedder, threshold=0.75)

    by_main = base.search("стиральная машина не отжимает")
    by_variant = base.search("стиралка машинка сломалась")

    assert by_main is not None and by_main[0].id == 1
    assert by_variant is not None and by_variant[0].id == 1


def test_variants_of_unmarked_records_stay_out_of_search():
    """Запись без уточняющего вопроса не участвует в поиске даже вариантами."""
    embedder = FakeEmbedder({"мусорная фраза": [1.0, 0.0, 0.0]})
    records = [
        KnowledgeRecord(id=1, question="мусорная фраза", question_variants=["мусорная фраза"]),
    ]
    base = KnowledgeBase(records, embedder, threshold=0.5)
    assert base.search("мусорная фраза") is None


def test_empty_variants_are_ignored():
    embedder = FakeEmbedder({"вопрос": [1.0, 0.0, 0.0]})
    records = [
        KnowledgeRecord(
            id=1,
            question="вопрос",
            question_variants=["", "   "],
            clarifying_question="Точно?",
        ),
    ]
    base = KnowledgeBase(records, embedder, threshold=0.5)
    found = base.search("вопрос")
    assert found is not None and found[0].id == 1


def test_knowledge_base_file_variants_are_loaded(tmp_path):
    import json

    source = [{
        "id": 7,
        "question": "течёт посудомойка",
        "question_variants": ["посудомоечная машина протекает"],
        "clarifying_question": "Речь о посудомоечной машине?",
        "positive_answers": ["да"],
        "negative_answers": ["нет"],
        "positive_reply": "Соединяю",
        "scenario": "redirect_sales",
        "equipment_type": "Посудомоечные машины",
    }]
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    embedder = FakeEmbedder({
        "течёт посудомойка": [1.0, 0.0, 0.0],
        "посудомоечная машина протекает": [1.0, 0.0, 0.0],
    })
    base = load_knowledge_base(str(path), embedder, threshold=0.75)
    found = base.search("посудомоечная машина протекает")
    assert found is not None and found[0].id == 7


def test_real_knowledge_base_has_variants_for_every_record():
    """Живая база обязана содержать синонимы: без них порог отсекает нормальную речь."""
    import json
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "knowledge_base.json"
    records = json.loads(path.read_text(encoding="utf-8"))

    assert records, "база знаний пуста"
    for record in records:
        variants = record.get("question_variants", [])
        assert len(variants) >= 3, (
            "у записи %s всего %s синонимов — живая речь так не покрывается"
            % (record["id"], len(variants))
        )


def test_record_with_scenario_but_no_clarifying_question_is_searchable():
    """«Соедините с оператором» приезжает из ERP без уточняющего вопроса и с
    готовым сценарием — искаться обязана (UL-19020). Реплика, записанная
    add() на разметку, сценария не имеет и в индекс по-прежнему не попадает."""
    from ai_assistant.service.knowledge import KnowledgeBase, KnowledgeRecord

    operator = KnowledgeRecord(id=47, question="переключить на оператора",
                               clarifying_question="", scenario="direction")
    raw = KnowledgeRecord(id=99, question="заказать пиццу", clarifying_question="")
    embedder = FakeEmbedder({"переключить на оператора": [1.0, 0.0, 0.0]})
    kb = KnowledgeBase([operator, raw], embedder, threshold=0.5)

    found = kb.best_match("переключить на оператора")

    assert found is not None and found[0].id == 47
    assert all(r.id != 99 for r in kb._searchable_records)


# --- корпус живых реплик как второе мнение (corpus_knn.py) ---------------------

def _unit(*coords):
    v = np.array(coords, dtype=np.float32)
    return v / np.linalg.norm(v)


def _corpus_base(corpus_threshold=0.6):
    from ai_assistant.service.corpus_knn import CorpusIndex

    washer = KnowledgeRecord(id=1, question="стиральная машина не отжимает",
                             clarifying_question="Ремонт стиральной машины?", telephone_direction_id=53)
    dryer = KnowledgeRecord(id=37, question="сушильная машина не сушит",
                            clarifying_question="Ремонт сушильной машины?", telephone_direction_id=53)
    complaint = KnowledgeRecord(id=28, question="мастер приезжал но техника снова не работает",
                                clarifying_question="У вас жалоба на ремонт?", telephone_direction_id=17)
    operator = KnowledgeRecord(id=63, question="соедините с оператором", clarifying_question="",
                               scenario="Соединить с оператором", telephone_direction_id=17)
    # Четыре оси: X — стиралки, Y — сопровождение, Z — сушилка, W — «что-то
    # ещё» (им реплика клиента отдаляется от формулировок, не меняя соседей).
    embedder = FakeEmbedder({
        "стиральная машина не отжимает": [1.0, 0.0, 0.0, 0.0],
        "сушильная машина не сушит": [0.9, 0.0, 0.44, 0.0],
        "мастер приезжал но техника снова не работает": [0.0, 1.0, 0.0, 0.0],
        "соедините с оператором": [0.0, 0.7, 0.0, 0.7],
        # реплики клиента
        "машинка чё-то того": [0.6, 0.0, 0.0, 0.8],       # к стиралке всего 0.6 — ниже порога 0.75
        "сушилка не сушит совсем": [0.85, 0.0, 0.5, 0.0],
        "мне мастер звонил": [0.0, 0.95, 0.3, 0.0],
        "не знаю что-то сломалось": [0.72, 0.69, 0.0, 0.0],  # ровно между стиралкой и сопровождением
    })
    # Корпус: три соседа про стиралки (ТН 53) у оси X, три про оператора (ТН 17) у оси Y.
    corpus = CorpusIndex(
        [_unit(1, 0.1, 0, 0), _unit(1, -0.1, 0, 0), _unit(1, 0, 0.1, 0),
         _unit(0, 1, 0.1, 0), _unit(0.1, 1, 0, 0), _unit(0, 1, 0, 0)],
        [53, 53, 53, 17, 17, 17],
        ["стиралка не крутит", "машинка течёт", "не отжимает", "жду мастера", "мастер звонил", "по заявке"],
        k=3, threshold=corpus_threshold)
    return KnowledgeBase([washer, dryer, complaint, operator], embedder, threshold=0.75, corpus=corpus)


def test_confident_corpus_vote_is_trusted_even_below_phrase_threshold():
    base = _corpus_base()

    found = base.resolve("машинка чё-то того")

    assert found.trusted and found.source == "corpus"
    assert found.record.id == 1
    assert found.score == pytest.approx(0.6, abs=0.01)
    assert found.vote.direction_id == 53 and found.vote.confidence > 0.9


def test_corpus_picks_the_closest_record_of_the_direction():
    """У одного направления две записи — берётся та, чья формулировка ближе."""
    base = _corpus_base()

    found = base.resolve("сушилка не сушит совсем")

    assert found.source == "corpus" and found.record.id == 37


def test_operator_direction_prefers_record_without_clarifying_question():
    """Повторное обращение уходит на оператора сразу, а не через вопрос про жалобу,
    хотя формулировка жалобы к реплике ближе."""
    base = _corpus_base()

    found = base.resolve("мне мастер звонил")

    assert found.trusted and found.source == "corpus"
    assert found.record.id == 63 and not found.record.clarifying_question


def test_unsure_corpus_leaves_the_decision_to_phrases():
    """Соседи разделились — корпус не дотягивает до порога уверенности, решает
    порог по формулировке."""
    base = _corpus_base(corpus_threshold=0.9)

    found = base.resolve("не знаю что-то сломалось")

    assert found.source == "phrases" and not found.trusted
    assert found.record.id == 1 and found.vote is not None
    assert found.vote.confidence < 0.9


def test_corpus_direction_without_a_record_falls_back_to_phrases():
    from ai_assistant.service.corpus_knn import CorpusIndex

    record = KnowledgeRecord(id=1, question="стиральная машина не отжимает",
                             clarifying_question="Ремонт?", telephone_direction_id=53)
    embedder = FakeEmbedder({"стиральная машина не отжимает": [1.0, 0.0, 0.0],
                             "проектор моргает": [0.0, 0.0, 1.0]})
    corpus = CorpusIndex([_unit(0, 0, 1)], [59], ["проектор не включается"], k=1, threshold=0.5)
    base = KnowledgeBase([record], embedder, threshold=0.75, corpus=corpus)

    found = base.resolve("проектор моргает")

    assert found.source == "phrases" and not found.trusted
    assert found.vote.direction_id == 59


def test_resolve_without_corpus_matches_best_match():
    record = KnowledgeRecord(id=1, question="стиральная машина не отжимает", clarifying_question="Ремонт?")
    embedder = FakeEmbedder({"стиральная машина не отжимает": [1.0, 0.0, 0.0],
                             "стиралка не отжимает": [0.95, 0.3, 0.0]})
    base = KnowledgeBase([record], embedder, threshold=0.75)

    found = base.resolve("стиралка не отжимает")
    match = base.best_match("стиралка не отжимает")

    assert found.record is match[0] and found.score == pytest.approx(match[1])
    assert found.trusted and found.source == "phrases" and found.vote is None
    assert base.resolve("   ") is None


# --- ограничения на голос корпуса (разбор второго этапа теста, 24.09.2026) ------------

def test_content_words_drop_greetings_and_fillers():
    from ai_assistant.service.knowledge import content_words

    assert content_words("угу здравствуйте") == []
    assert content_words("да алло здрасьте") == []
    assert content_words("Здравствуйте, у нас сломалась духовка") == ["сломалась", "духовка"]
    assert content_words("вызвать мастера на на дом") == ["вызвать", "мастера", "дом"]


def test_corpus_does_not_vote_on_content_free_utterance():
    """«Угу здравствуйте» уходило на оператора: соседи — такие же пустые начала
    повторных звонков. Теперь такая реплика корпусу не показывается."""
    base = _corpus_base()

    found = base.resolve("мне мастер звонил")           # два содержательных слова — голос есть
    empty = base.resolve_vector(base._embedder.encode(["search_query: мне мастер звонил"])[0], content_words=1)

    assert found.source == "corpus"
    assert empty.source == "phrases"


def test_operator_needs_a_higher_confidence_than_a_subject():
    from ai_assistant.service.corpus_knn import CorpusIndex

    record = KnowledgeRecord(id=63, question="соедините с оператором", clarifying_question="",
                             scenario="Соединить с оператором", telephone_direction_id=17)
    washer = KnowledgeRecord(id=1, question="стиральная машина не отжимает",
                             clarifying_question="Ремонт?", telephone_direction_id=53)
    embedder = FakeEmbedder({"соедините с оператором": [0.0, 1.0, 0.0],
                             "стиральная машина не отжимает": [1.0, 0.0, 0.0],
                             "вызвать мастера на дом": [0.3, 0.95, 0.0],
                             "стиралка не крутит": [0.95, 0.3, 0.0]})
    # Соседи с весом близость^4: при «вызвать мастера» 6 за оператора (вес 1)
    # и 4 за стиралки (вес ~0.85) — уверенность ~0.64, ниже порога оператора.
    vectors = [_unit(0.3, 0.95, 0.0)] * 6 + [_unit(0.55, 0.83, 0.0)] * 4
    corpus = CorpusIndex(vectors, [17] * 6 + [53] * 4, ["x"] * 10, k=10, threshold=0.5, operator_threshold=0.8)
    base = KnowledgeBase([record, washer], embedder, threshold=0.75, corpus=corpus)

    operator = base.resolve("вызвать мастера на дом")
    subject = base.resolve("стиралка не крутит")

    # Неуверенный оператор — не к формулировкам, а переспросить: записи нет,
    # решению не верим, но голос в резолюции остаётся для лога.
    assert 0.5 <= operator.vote.confidence < 0.8
    assert operator.source == "corpus-unsure" and operator.record is None and not operator.trusted
    assert subject.source == "corpus" and subject.record.id == 1
