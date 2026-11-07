"""The learning and recognition contract (docs/PLAN-LEARNING.md §10): the signatures the lead's
step fixed, which the other packages call. The packages fill the bodies and keep these exactly;
what the functions do is tested next to them."""

import inspect

import pytest

from apps.learning import conf, courses, queries, skills
from apps.recognition import queries as recognition_queries
from apps.recognition import services as recognition

K = inspect.Parameter.KEYWORD_ONLY
P = inspect.Parameter.POSITIONAL_OR_KEYWORD
EMPTY = inspect.Parameter.empty

CONTRACT = {
    courses.assign: [
        ("course", P, EMPTY),
        ("members", P, EMPTY),
        ("by", K, EMPTY),
        ("source", K, "manual"),
        ("due_at", K, None),
    ],
    courses.on_attempt_finished: [("attempt", P, EMPTY)],
    queries.compliance: [("company", P, EMPTY), ("branch_ids", K, EMPTY), ("now", K, None)],
    queries.open_assignments: [("member", P, EMPTY)],
    queries.courses_for_topic: [("company", P, EMPTY), ("topic_id", P, EMPTY)],
    queries.lessons_for_topic: [("company", P, EMPTY), ("topic_id", P, EMPTY)],
    queries.can_open_lesson: [("member", P, EMPTY), ("lesson", P, EMPTY)],
    skills.mastery: [
        ("company", P, EMPTY),
        ("member_ids", K, None),
        ("topic_ids", K, None),
        ("since", K, None),
    ],
    conf.get_settings: [("company", P, EMPTY)],
    conf.is_on: [("company", P, EMPTY)],
    recognition.award: [
        ("member", P, EMPTY),
        ("reason", K, EMPTY),
        ("key", K, EMPTY),
        ("points", K, None),
        ("note", K, ""),
        ("at", K, None),
        ("by", K, None),
    ],
    recognition.touch_streak: [("member", P, EMPTY), ("day", P, EMPTY), ("kind", K, "learning")],
    recognition_queries.summary: [("member", P, EMPTY)],
    recognition_queries.levels: [],
}


@pytest.mark.parametrize("function", CONTRACT, ids=lambda function: function.__qualname__)
def test_signature(function):
    found = [
        (name, parameter.kind, parameter.default)
        for name, parameter in inspect.signature(function).parameters.items()
    ]
    assert found == CONTRACT[function]


def test_skills_bands_are_fixed():
    assert (skills.MIN_ANSWERS, skills.WEAK, skills.STRONG) == (3, 60, 85)
