"""Leaderboards (PLAN-LEARNING §7.6) and the summary/levels contract (§10)."""

from datetime import date, timedelta

import pytest

from apps.recognition import conf, queries
from apps.recognition.tests.conftest import DAY, at
from apps.recognition.tests.factories import BadgeAwardFactory, PointsEntryFactory, StreakFactory

pytestmark = pytest.mark.django_db
MONDAY = date(2026, 11, 2)


def give(member, points, day, hour=12, reason="quiz"):
    return PointsEntryFactory(
        membership=member,
        points=points,
        reason=reason,
        at=at(day, hour),
        key=f"t:{member.pk}:{day}:{hour}:{points}",
    )


def names(board):
    return [row.member.first_name for row in board.rows]


def test_periods_and_ties_go_to_who_got_there_first(shop, ali, madina, nigora, head):
    give(ali, 30, MONDAY, 9)
    give(madina, 30, MONDAY, 8)  # the same points, earlier
    give(nigora, 50, MONDAY - timedelta(days=3))  # last week (October)
    give(head, 0, MONDAY, reason="lesson")  # worth nothing: not listed
    week = queries.leaderboard(shop, period="week", branch_ids=None)
    assert names(week) == ["Madina", "Alisher"]
    assert [row.place for row in week.rows] == [1, 2]
    assert names(queries.leaderboard(shop, period="month", branch_ids=None)) == [
        "Madina",
        "Alisher",
    ]
    assert names(queries.leaderboard(shop, period="all", branch_ids=None)) == [
        "Nigora",
        "Madina",
        "Alisher",
    ]
    october = queries.leaderboard(shop, period="month", branch_ids=None, day=date(2026, 10, 3))
    assert names(october) == ["Nigora"]
    assert week.start == at(MONDAY, 0) and week.end == at(MONDAY + timedelta(days=7), 0)


def test_negative_totals_are_not_listed_and_levels_are_all_time(shop, ali, madina):
    give(ali, 400, MONDAY - timedelta(days=30))
    give(ali, 20, MONDAY)
    give(madina, 10, MONDAY)
    give(madina, -50, MONDAY, 13, reason="adjust")
    board = queries.leaderboard(shop, period="week", branch_ids=None)
    assert names(board) == ["Alisher"]
    assert board.rows[0].points == 20 and board.rows[0].level.number == 3


def test_branch_scope_and_learning_points(shop, ali, nigora, chilonzor, yunusobod):
    give(ali, 20, MONDAY, reason="task")
    give(nigora, 15, MONDAY, reason="lesson")
    assert names(queries.leaderboard(shop, period="week", branch_ids=[yunusobod.pk])) == ["Nigora"]
    assert names(queries.leaderboard(shop, period="week", branch_ids=[])) == []
    learning = queries.leaderboard(
        shop, period="week", branch_ids=None, reasons=queries.LEARNING_REASONS
    )
    assert names(learning) == ["Nigora"]


def test_staff_see_the_top_ten_and_their_place(shop, member, ali, chilonzor):
    people = [member(shop, "Pharmacist", first_name=f"P{index}") for index in range(12)]
    for index, person in enumerate(people):
        give(person, 100 - index, MONDAY)
    give(ali, 1, MONDAY)
    board = queries.staff_board(ali, period="week")
    assert board["visible"] and len(board["rows"]) == 10
    assert board["me"] == {"place": 13, "points": 1}
    assert board["rows"][0]["member"]["id"] == people[0].pk


def test_staff_board_off_and_branch_scope(shop, ali, nigora, madina, head):
    give(nigora, 50, MONDAY)
    give(madina, 20, MONDAY)
    give(ali, 10, MONDAY)
    settings = conf.get_settings(shop)
    settings.leaderboard_scope = settings.Scope.BRANCH
    settings.save()
    board = queries.staff_board(ali, period="week", scope="company")
    assert board["scope"] == "branch"
    assert [row["member"]["id"] for row in board["rows"]] == [madina.pk, ali.pk]
    settings.leaderboard_for_staff = False
    settings.save()
    hidden = queries.staff_board(ali, period="week")
    assert hidden["visible"] is False and hidden["rows"] == []
    assert hidden["me"] == {"place": None, "points": 10}
    # A manager sees everyone they see (their branch scope), whatever the staff setting.
    manager = queries.staff_board(head, period="week")
    assert manager["visible"] and [row["member"]["id"] for row in manager["rows"]] == [
        madina.pk,
        ali.pk,
    ]


def test_the_export_follows_the_filters_and_the_scope(shop, owner, head, ali, nigora, yunusobod):
    from apps.recognition import providers

    give(ali, 30, MONDAY)
    give(nigora, 50, MONDAY, reason="lesson")
    rows = list(providers.leaderboard_rows(owner, {"period": "week"}))
    assert [row["name"] for row in rows] == ["Nigora Azimova", "Alisher Valiyev"]
    assert rows[0] == {
        "place": 1,
        "name": "Nigora Azimova",
        "position": "",
        "points": 50,
        "level": 1,
        "level_name": "Newcomer",
    }
    only = list(providers.leaderboard_rows(owner, {"period": "week", "branch": str(yunusobod.pk)}))
    assert [row["name"] for row in only] == ["Nigora Azimova"]
    # The head sees Chilonzor only, whatever the filter asks.
    assert [row["name"] for row in providers.leaderboard_rows(head, {"branch": yunusobod.pk})] == [
        "Alisher Valiyev"
    ]


def test_summary_and_levels_contract(shop, ali, freeze):
    give(ali, 300, MONDAY - timedelta(days=10))
    give(ali, 40, MONDAY + timedelta(days=1))
    StreakFactory(membership=ali, current=4, best=9, last_day=DAY - timedelta(days=1))
    BadgeAwardFactory(membership=ali, badge="first_lesson", awarded_at=at(MONDAY))
    BadgeAwardFactory(membership=ali, badge="first_quiz", awarded_at=at(MONDAY, 15))
    summary = queries.summary(ali)
    assert (summary.points, summary.week_points) == (340, 40)
    assert (summary.level.number, summary.level.name, summary.level.next_at) == (3, "Active", 500)
    assert (summary.streak, summary.best_streak, summary.badges) == (4, 9, 2)
    assert summary.badge_keys == ["first_quiz", "first_lesson"]
    assert len(queries.levels()) == 10
    shop.features = ["learning"]
    shop.save(update_fields=["features"])
    assert queries.summary(ali) is None
