import pytest

from bot.config import TopicConfig
from bot.services.scoring import compute_scores, find_weak_topic

# Minimal topic graph mirroring config.yaml:
# A1 → A2 → A3
# A1, A2 → S
# G1 → G2
TOPICS: dict[str, TopicConfig] = {
    "A1": TopicConfig(name="Арифметика", dependencies=[], in_ege_part1=True),
    "A2": TopicConfig(name="Рациональные числа", dependencies=["A1"], in_ege_part1=True),
    "A3": TopicConfig(name="Линейные уравнения", dependencies=["A2"], in_ege_part1=True),
    "S":  TopicConfig(name="Вероятность", dependencies=["A1", "A2"], in_ege_part1=True),
    "G1": TopicConfig(name="Основы геометрии", dependencies=[], in_ege_part1=True),
    "G2": TopicConfig(name="Треугольники", dependencies=["G1"], in_ege_part1=True),
}

# dependents[A1]=[A2,S], dependents[A2]=[A3,S], dependents[G1]=[G2]
# 1-hop of A1 = {A2,S}; 2-hop of A1 = {A3} (S excluded, already at 1-hop)
# 1-hop of G1 = {G2}; 2-hop of G1 = {}


def scores(answers: list[dict]) -> dict[str, float]:
    return compute_scores(answers, TOPICS)


class TestAllCorrect:
    def test_all_correct_is_100(self):
        answers = [{"topic_code": t, "result": "correct"} for t in TOPICS]
        s = scores(answers)
        assert all(v == 100.0 for v in s.values())

    def test_empty_answers_all_100(self):
        # no answers → all default correct → all ≥ 0 → 100%
        s = scores([])
        assert all(v == 100.0 for v in s.values())


class TestA1Wrong:
    # A1 wrong: base=-1, 1-hop={A2 correct +0.25, S correct +0.25},
    #            2-hop={A3 correct +0.125}  → score=-0.375 → pct=62.5%
    def test_a1_pct(self):
        s = scores([{"topic_code": "A1", "result": "wrong"}])
        assert s["A1"] == pytest.approx(62.5)

    def test_others_unaffected(self):
        s = scores([{"topic_code": "A1", "result": "wrong"}])
        for t in ("A2", "A3", "S", "G1", "G2"):
            assert s[t] == pytest.approx(100.0), f"{t} should be 100%"


class TestG1Wrong:
    # G1 wrong: base=-1, 1-hop={G2 correct +0.25}, 2-hop={}
    # score=-0.75 → pct=25%
    def test_g1_pct(self):
        s = scores([{"topic_code": "G1", "result": "wrong"}])
        assert s["G1"] == pytest.approx(25.0)

    def test_algebra_unaffected(self):
        s = scores([{"topic_code": "G1", "result": "wrong"}])
        for t in ("A1", "A2", "A3", "S", "G2"):
            assert s[t] == pytest.approx(100.0), f"{t} should be 100%"


class TestA1A2BothWrong:
    # A1: base=-1; A2 wrong→-0.5; S correct→+0.25; A3 correct→+0.125
    #   score=-1.125 → pct=0%
    # A2: base=-1; A3 correct→+0.25; S correct→+0.25; 2-hop={}
    #   score=-0.5 → pct=50%
    def test_a1_zeroed(self):
        s = scores([
            {"topic_code": "A1", "result": "wrong"},
            {"topic_code": "A2", "result": "wrong"},
        ])
        assert s["A1"] == pytest.approx(0.0)

    def test_a2_pct(self):
        s = scores([
            {"topic_code": "A1", "result": "wrong"},
            {"topic_code": "A2", "result": "wrong"},
        ])
        assert s["A2"] == pytest.approx(50.0)

    def test_others_100(self):
        s = scores([
            {"topic_code": "A1", "result": "wrong"},
            {"topic_code": "A2", "result": "wrong"},
        ])
        for t in ("A3", "S", "G1", "G2"):
            assert s[t] == pytest.approx(100.0)


class TestG1G2BothWrong:
    # G1: base=-1; G2 wrong→-0.5; score=-1.5 → pct=0%
    # G2: base=-1; 1-hop={}; score=-1 → pct=0%
    def test_g1_zeroed(self):
        s = scores([
            {"topic_code": "G1", "result": "wrong"},
            {"topic_code": "G2", "result": "wrong"},
        ])
        assert s["G1"] == pytest.approx(0.0)

    def test_g2_zeroed(self):
        s = scores([
            {"topic_code": "G1", "result": "wrong"},
            {"topic_code": "G2", "result": "wrong"},
        ])
        assert s["G2"] == pytest.approx(0.0)


class TestScoreFormula:
    def test_score_between_minus1_and_0_uses_linear(self):
        # A1 wrong alone: score=-0.375 → (1-0.375)*100=62.5
        s = scores([{"topic_code": "A1", "result": "wrong"}])
        assert s["A1"] == pytest.approx(62.5)

    def test_score_exactly_minus1_gives_0pct(self):
        # G2 wrong alone: base=-1, 1-hop={}, 2-hop={} → score=-1.0 → 0%
        s = scores([{"topic_code": "G2", "result": "wrong"}])
        assert s["G2"] == pytest.approx(0.0)

    def test_skip_same_as_wrong(self):
        # skip treated as non-correct (base=-1)
        s_skip = scores([{"topic_code": "G1", "result": "skip"}])
        s_wrong = scores([{"topic_code": "G1", "result": "wrong"}])
        assert s_skip["G1"] == pytest.approx(s_wrong["G1"])

    def test_timeout_same_as_wrong(self):
        s_timeout = scores([{"topic_code": "G1", "result": "timeout"}])
        s_wrong = scores([{"topic_code": "G1", "result": "wrong"}])
        assert s_timeout["G1"] == pytest.approx(s_wrong["G1"])


class TestFindWeakTopic:
    def test_g1_wrong_returns_g1(self):
        # G1 at layer-0 pct=25% < 50 → returned immediately
        s = scores([{"topic_code": "G1", "result": "wrong"}])
        assert find_weak_topic(s, TOPICS) == "G1"

    def test_a1_wrong_fallback_to_min(self):
        # A1 wrong: pct=62.5%, no topic < 50% → fallback = argmin = A1
        s = scores([{"topic_code": "A1", "result": "wrong"}])
        assert find_weak_topic(s, TOPICS) == "A1"

    def test_a1_a2_both_wrong_returns_a1(self):
        # A1=0% at layer-0 → returned first before G1 check
        s = scores([
            {"topic_code": "A1", "result": "wrong"},
            {"topic_code": "A2", "result": "wrong"},
        ])
        assert find_weak_topic(s, TOPICS) == "A1"

    def test_all_correct_returns_valid_topic(self):
        s = {t: 100.0 for t in TOPICS}
        result = find_weak_topic(s, TOPICS)
        assert result in TOPICS


class TestUnknownTopic:
    def test_unknown_topic_ignored(self):
        s = scores([{"topic_code": "UNKNOWN", "result": "wrong"}])
        assert all(v == 100.0 for v in s.values())
