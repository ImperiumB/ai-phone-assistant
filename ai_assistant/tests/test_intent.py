"""Ярус намерения: вероятности, загрузка модели и место стадии в резолвере."""
import io
import json

import numpy as np
import pytest

from ai_assistant.service.intent import IntentModel, load_intent_model
from ai_assistant.service.knowledge import KnowledgeBase, KnowledgeRecord


def model_for(repeat_weight=4.0):
    """Модель на трёх измерениях: второе измерение тянет в класс «повторное»."""
    coef = [
        [2.0, 0.0, 0.0],            # N: тянет первое измерение
        [0.0, repeat_weight, 0.0],  # R: тянет второе
        [0.0, 0.0, 2.0],            # X: тянет третье
    ]
    return IntentModel(classes=["N", "R", "X"], coef=coef, intercept=[0.0, 0.0, 0.0])


def test_probabilities_sum_to_one_and_pick_the_leading_class():
    model = model_for()
    probabilities = model.probabilities(np.array([0.0, 1.0, 0.0], dtype=np.float32))
    assert pytest.approx(float(probabilities.sum()), abs=1e-6) == 1.0
    assert model.classes[int(np.argmax(probabilities))] == "R"


def test_repeat_probability_grows_with_the_repeat_direction():
    model = model_for()
    low = model.repeat_probability(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    high = model.repeat_probability(np.array([0.0, 1.0, 0.0], dtype=np.float32))
    assert high > low
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0


def test_repeat_probability_is_zero_without_the_repeat_class():
    model = IntentModel(classes=["N", "X"], coef=[[1.0, 0.0], [0.0, 1.0]], intercept=[0.0, 0.0])
    assert model.repeat_probability(np.array([1.0, 0.0], dtype=np.float32)) == 0.0


def test_missing_model_file_is_not_an_error(tmp_path):
    """Нет файла это обычное состояние установки без яруса, а не отказ."""
    assert load_intent_model(str(tmp_path / "нет.json")) is None
    assert load_intent_model("") is None


def test_broken_model_file_turns_the_tier_off_instead_of_crashing(tmp_path):
    path = tmp_path / "intent.json"
    path.write_text("{это не json", encoding="utf-8")
    assert load_intent_model(str(path)) is None


def test_model_with_a_wrong_vector_length_is_refused(tmp_path):
    path = tmp_path / "intent.json"
    payload = {"classes": ["N", "R"], "coef": [[1.0, 0.0], [0.0, 1.0]], "intercept": [0.0, 0.0]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_intent_model(str(path), expected_dim=1024) is None
    assert load_intent_model(str(path), expected_dim=2) is not None


def test_model_round_trips_through_the_file(tmp_path):
    path = tmp_path / "intent.json"
    payload = {
        "classes": ["N", "R", "X"],
        "coef": [[2.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 2.0]],
        "intercept": [0.0, 0.0, 0.0],
        "embedder": "ai-forever/ru-en-RoSBERTa",
        "trained_at": "2026-11-07T12:00:00",
    }
    with io.open(str(path), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    model = load_intent_model(str(path), expected_dim=3, expected_embedder="ai-forever/ru-en-RoSBERTa")
    assert model is not None
    assert model.classes == ["N", "R", "X"]
    assert model.repeat_probability(np.array([0.0, 1.0, 0.0], dtype=np.float32)) > 0.5


class StubEmbedder:
    """Кодирует реплику в заданный вектор: «заказ» тянет в повторное обращение."""

    def encode(self, texts):
        out = []
        for text in texts:
            repeat = 1.0 if "заказ" in text else 0.0
            out.append(np.array([1.0 - repeat, repeat, 0.0], dtype=np.float32))
        return np.stack(out)


def base_with_tier(intent, threshold=0.70):
    records = [
        KnowledgeRecord(
            id=1, scenario="Стиральные машины", question="стиральная машина не отжимает",
            question_variants=["ремонт стиральной машины"],
            clarifying_question="Правильно понимаю, что вас интересует ремонт стиральной машины?",
            positive_reply="Соединяю", redirect_exten="7238",
        ),
        # Запись оператора, как в боевой базе: у неё нет уточняющего вопроса
        # (перевод к человеку сразу) и есть однословная формулировка, по основе
        # которой её находят и стадия ключевых слов, и ярус намерения
        # (_collect_direct_keywords берёт только однословные формулировки).
        KnowledgeRecord(
            id=61, scenario="Сопровождение", question="соедините с оператором",
            question_variants=["оператор", "оператора"],
            clarifying_question="", positive_reply="", redirect_exten="7082",
        ),
    ]
    return KnowledgeBase(records, StubEmbedder(), threshold=0.6, corpus=None,
                         intent=intent, intent_repeat_threshold=threshold)


def test_tier_sends_a_repeat_request_to_a_human():
    """Повторное обращение уходит к человеку, а не получает вопрос про прибор."""
    resolution = base_with_tier(model_for()).resolve("я у вас заказ оформлял")
    assert resolution is not None
    assert resolution.source == "intent"
    assert resolution.record.id == 61
    assert resolution.trusted


def test_tier_keeps_a_new_order_on_the_usual_path():
    """Замок приёмки: новый заказ ярус не забирает."""
    resolution = base_with_tier(model_for()).resolve("ремонт стиральной машины")
    assert resolution is not None
    assert resolution.source != "intent"
    assert resolution.record.id == 1


def test_tier_is_silent_when_disabled():
    resolution = base_with_tier(None).resolve("я у вас заказ оформлял")
    assert resolution is None or resolution.source != "intent"


def test_tier_respects_its_threshold():
    """Порог решает: при высоком пороге та же реплика идёт обычным путём."""
    resolution = base_with_tier(model_for(), threshold=0.99).resolve("я у вас заказ оформлял")
    assert resolution is None or resolution.source != "intent"


def test_explicit_operator_request_wins_over_the_tier():
    """Явная просьба позвать человека решается раньше и без модели."""
    resolution = base_with_tier(model_for()).resolve("соедините с оператором пожалуйста")
    assert resolution is not None
    assert resolution.source == "keyword"
    assert resolution.record.id == 61
