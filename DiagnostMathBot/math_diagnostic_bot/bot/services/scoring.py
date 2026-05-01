import logging
from collections import deque

from bot.config import TopicConfig

logger = logging.getLogger(__name__)


def compute_scores(
    answers: list[dict],
    topics: dict[str, TopicConfig],
) -> dict[str, float]:
    """Per-topic score from answer results + 1- and 2-hop dependent answers.

    Score formula per topic:
        base = 0 if correct else -1
        + correct_1hop * 0.25  - wrong_1hop * 0.5
        + correct_2hop * 0.125 - wrong_2hop * 0.25

    pct conversion:
        score <= -1  → 0%
        score >=  0  → 100%
        otherwise   → (1 + score) * 100%
    """
    answers_by_topic: dict[str, str] = {}
    for a in answers:
        code = a.get("topic_code")
        if code in topics:
            answers_by_topic[code] = a.get("result", "correct")

    # outgoing edges: dependents[X] = topics that directly depend on X
    dependents: dict[str, list[str]] = {t: [] for t in topics}
    for code, topic in topics.items():
        for dep in topic.dependencies:
            if dep in dependents:
                dependents[dep].append(code)

    scores: dict[str, float] = {}
    for topic_code in topics:
        result = answers_by_topic.get(topic_code, "correct")
        base = 0 if result == "correct" else -1

        one_step: set[str] = set(dependents.get(topic_code, []))
        two_step: set[str] = {
            gc
            for c in one_step
            for gc in dependents.get(c, [])
            if gc not in one_step
        }

        score = float(base)
        for dep in one_step:
            dep_result = answers_by_topic.get(dep, "correct")
            score += 0.25 if dep_result == "correct" else -0.5
        for dep in two_step:
            dep_result = answers_by_topic.get(dep, "correct")
            score += 0.125 if dep_result == "correct" else -0.25

        if score <= -1.0:
            pct = 0.0
        elif score >= 0.0:
            pct = 100.0
        else:
            pct = (1.0 + score) * 100.0

        scores[topic_code] = pct

    return scores


def find_weak_topic(scores: dict[str, float], topics: dict[str, TopicConfig]) -> str:
    """BFS from A1 and G1; return first topic with pct < 50. Fallback: global min."""
    dependents: dict[str, list[str]] = {t: [] for t in topics}
    for code, topic in topics.items():
        for dep in topic.dependencies:
            if dep in dependents:
                dependents[dep].append(code)

    roots = [r for r in ("A1", "G1") if r in topics]
    if not roots:
        return min(scores, key=lambda t: scores[t])

    visited: set[str] = set(roots)
    current_layer: list[str] = list(roots)

    while current_layer:
        for node in current_layer:
            if scores.get(node, 100.0) < 50.0:
                return node
        next_layer: list[str] = []
        for node in current_layer:
            for child in dependents.get(node, []):
                if child not in visited:
                    visited.add(child)
                    next_layer.append(child)
        current_layer = next_layer

    return min(scores, key=lambda t: scores[t])
