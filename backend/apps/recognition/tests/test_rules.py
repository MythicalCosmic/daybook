"""The numbers of recognition: the points table and the ten levels (PLAN-LEARNING §7.1, §7.2)."""

import pytest
from django.utils import translation

from apps.recognition import badges, queries, rules


@pytest.mark.parametrize(
    ("total", "number"),
    [
        (0, 1),
        (-40, 1),
        (99, 1),
        (100, 2),
        (249, 2),
        (250, 3),
        (499, 3),
        (500, 4),
        (999, 4),
        (1000, 5),
        (2000, 6),
        (3499, 6),
        (3500, 7),
        (5500, 8),
        (7999, 8),
        (8000, 9),
        (11999, 9),
        (12000, 10),
        (90000, 10),
    ],
)
def test_levels_by_total(total, number):
    assert rules.level_number(total) == number


def test_ten_levels_with_their_names_in_three_languages():
    with translation.override("en"):
        assert [level.name for level in queries.levels()] == [
            "Newcomer",
            "Learner",
            "Active",
            "Knowledgeable",
            "Experienced",
            "Specialist",
            "Mentor",
            "Expert",
            "Master",
            "Legend",
        ]
    with translation.override("uz"):
        names = [level.name for level in queries.levels()]
        assert names[1] == "O‘rganuvchi" and names[6] == "Ustoz" and names[9] == "Afsona"
    with translation.override("ru"):
        assert queries.levels()[3].name == "Знаток"
    levels = queries.levels()
    assert [level.starts_at for level in levels] == list(rules.LEVELS)
    assert [level.next_at for level in levels] == [*rules.LEVELS[1:], None]
    assert queries.level_of(740).number == 4 and queries.level_of(740).next_at == 1000


def test_points_table_defaults_and_company_rows():
    assert rules.points_for(None, "quiz") == 20
    assert rules.points_for(None, "daily") == 5 and rules.points_for(None, "daily_tried") == 1
    assert rules.points_for(None, "streak_100") == 300
    assert rules.points_for(None, "adjust") == 0
    assert rules.table({"quiz": 25, "lesson": "x", "nope": 4, "task": 5000})["quiz"] == 25
    assert rules.table({"lesson": "x"})["lesson"] == 10
    assert rules.table({"task": 5000})["task"] == rules.MAX_POINTS


def test_clean_table_keeps_only_changed_rows():
    assert rules.clean_table({"quiz": 25, "lesson": 10}) == {"quiz": 25}
    for bad in ({"quiz": -1}, {"quiz": 1001}, {"nope": 3}, {"quiz": True}, {"quiz": "5"}, []):
        with pytest.raises(ValueError):
            rules.clean_table(bad)


def test_badge_catalogue_is_complete():
    keys = [badge.key for badge in badges.BADGES]
    assert keys == [
        "first_lesson",
        "first_quiz",
        "perfect_score",
        "course_finisher",
        "five_courses",
        "streak_7",
        "streak_30",
        "streak_100",
        "daily_10",
        "topic_expert",
        "early_bird",
        "helper",
        "thanked",
        "on_time_week",
        "top3_month",
    ]
    for badge in badges.BADGES:
        assert badge.tier in badges.TIERS and badge.icon
        for code in ("en", "uz", "ru"):
            assert badge.names[code] and badge.descriptions[code]
        assert "'" not in badge.names["uz"] + badge.descriptions["uz"]
    assert {key for key, badge in badges.CATALOGUE.items() if badge.per_ref} == {
        "topic_expert",
        "top3_month",
    }


def test_badge_titles_with_their_topic_or_month():
    with translation.override("en"):
        assert badges.title("top3_month", "2026-11") == "Top three of the month: November 2026"
        assert badges.title("topic_expert", "4", topic="Cold chain") == "Topic expert: Cold chain"
    with translation.override("uz"):
        assert badges.title("top3_month", "2026-11").endswith("2026-yil noyabr")
    with translation.override("ru"):
        assert badges.title("top3_month", "2026-01").endswith("январь 2026")
