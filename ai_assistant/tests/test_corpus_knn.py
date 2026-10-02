import numpy as np
import pytest

from ai_assistant.service.corpus_knn import OPERATOR_DIRECTION, CorpusIndex


def unit(*coords):
    v = np.array(coords, dtype=np.float32)
    return v / np.linalg.norm(v)


def index(k=3, threshold=0.6):
    # Три реплики про стиралки (ТН 53) вокруг оси X, две про сопровождение (ТН 17) вокруг оси Y.
    vectors = [unit(1, 0.05, 0), unit(1, -0.05, 0), unit(0.95, 0.1, 0), unit(0, 1, 0), unit(0.05, 1, 0)]
    directions = [53, 53, 53, 17, 17]
    phrases = ["стиралка не крутит", "машинка течёт", "не отжимает", "мастер звонил", "жду мастера"]
    return CorpusIndex(vectors, directions, phrases, k=k, threshold=threshold)


def test_neighbours_vote_for_their_direction():
    vote = index().vote(unit(1, 0, 0))

    assert vote.direction_id == 53
    assert vote.confidence > 0.99
    assert [n.direction_id for n in vote.neighbours] == [53, 53, 53]
    assert vote.neighbours[0].score >= vote.neighbours[-1].score


def test_confidence_is_split_when_neighbours_disagree():
    # Запрос ровно между осями: среди 3 соседей два класса, уверенность не единица.
    vote = index(k=4).vote(unit(1, 1, 0))

    assert 0.3 < vote.confidence < 0.7


def test_closer_neighbours_weigh_more():
    # Один близкий сосед про оператора против двух далёких про стиралки.
    idx = CorpusIndex([unit(0, 1, 0), unit(1, 0.9, 0), unit(1, 0.9, 0)], [17, 53, 53], ["a", "b", "c"], k=3)

    vote = idx.vote(unit(0.05, 1, 0))

    assert vote.direction_id == OPERATOR_DIRECTION


def test_empty_index_votes_nothing():
    assert CorpusIndex(np.zeros((0, 3)), [], []).vote(unit(1, 0, 0)) is None
    assert len(CorpusIndex(np.zeros((0, 3)), [], [])) == 0


def test_k_larger_than_index_is_fine():
    vote = index(k=50).vote(unit(1, 0, 0))

    assert vote.direction_id == 53
    assert len(vote.neighbours) == 5


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        CorpusIndex([unit(1, 0, 0)], [53, 17], ["a"])


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "corpus.npz")
    CorpusIndex.save(path, [unit(1, 0, 0), unit(0, 1, 0)], [53, 17], ["стиралка", "мастер звонил"], ["u1", "u2"])

    loaded = CorpusIndex.load(path, k=1, threshold=0.5)
    vote = loaded.vote(unit(0, 1, 0))

    assert len(loaded) == 2 and loaded.k == 1 and loaded.threshold == 0.5
    assert vote.direction_id == 17 and vote.neighbours[0].phrase == "мастер звонил"
