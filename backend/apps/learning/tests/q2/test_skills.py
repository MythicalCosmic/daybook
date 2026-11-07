"""Mastery and the skill matrix (docs/PLAN-LEARNING.md §4.6): golden numbers."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.companies.tests.factories import BranchFactory
from apps.learning import skills
from apps.learning.models import AnswerLog, Question
from apps.learning.tests.q2.fixtures import branch_viewer, person, position, question, topic

pytestmark = pytest.mark.django_db


def answers(member, topic_row, shares, *, start=None):
    """Answers in `topic_row` with these shares, oldest first, an hour apart."""
    start = start or timezone.now() - timedelta(days=10)
    asked = question(member.company, "true_false", topic=topic_row)
    for index, share in enumerate(shares):
        AnswerLog.objects.create(
            company=member.company,
            membership=member,
            question=asked,
            topic=topic_row,
            source="attempt",
            correct=share == 1,
            share=share,
            at=start + timedelta(hours=index),
        )


@pytest.mark.parametrize(
    ("shares_oldest_first", "score", "band"),
    [
        ([1, 0, 1], 67, "ok"),  # (1 + 0 + 0.7225) / 2.5725
        ([0, 1, 1], 72, "ok"),  # the newest weigh most: (1 + 0.85 + 0) / 2.5725
        ([1, 1, 0], 61, "ok"),
        ([0, 0, 1], 39, "weak"),
        ([1, 1, 1], 100, "strong"),
        ([0.5, 0.5, 0.5, 0.5], 50, "weak"),
        ([1, 1, 1, 0.5], 84, "ok"),
        ([0, 1, 1, 1, 1], 86, "strong"),  # 3.1866 / 3.7086
        ([0, 0, 1, 1, 1, 1], 77, "ok"),
    ],
)
def test_mastery_is_the_weighted_share_of_the_recent_answers(
    pharmacy, staff, shares_oldest_first, score, band
):
    cold = topic(pharmacy)
    answers(staff, cold, shares_oldest_first)
    found = skills.mastery(pharmacy)[(staff.pk, cold.pk)]
    assert (found.score, found.band, found.answers) == (score, band, len(shares_oldest_first))


def test_fewer_than_three_answers_are_unrated(pharmacy, staff):
    cold = topic(pharmacy)
    answers(staff, cold, [1, 1])
    found = skills.mastery(pharmacy)[(staff.pk, cold.pk)]
    assert (found.score, found.band, found.answers) == (None, "unrated", 2)
    assert found.last_at is not None


def test_only_the_last_twenty_answers_count(pharmacy, staff):
    cold = topic(pharmacy)
    answers(staff, cold, [0] * 5 + [1] * 20)
    found = skills.mastery(pharmacy)[(staff.pk, cold.pk)]
    assert (found.score, found.answers) == (100, 25)


def test_the_bands_are_fixed():
    assert [skills.band(score) for score in (None, 0, 59, 60, 84, 85, 100)] == [
        "unrated",
        "weak",
        "weak",
        "ok",
        "ok",
        "strong",
        "strong",
    ]


def test_mastery_filters_people_topics_and_time(pharmacy, staff):
    cold, rx = topic(pharmacy), topic(pharmacy, "Retsept")
    other = person(pharmacy)
    answers(staff, cold, [1, 1, 1])
    answers(staff, rx, [0, 0, 0])
    answers(other, cold, [0, 0, 0])
    assert set(skills.mastery(pharmacy, member_ids=[staff.pk])) == {
        (staff.pk, cold.pk),
        (staff.pk, rx.pk),
    }
    assert set(skills.mastery(pharmacy, topic_ids=[rx.pk])) == {(staff.pk, rx.pk)}
    since = timezone.now() - timedelta(days=10) + timedelta(minutes=90)
    later = skills.mastery(pharmacy, since=since)
    assert later[(staff.pk, cold.pk)].answers == 1


def test_a_topic_changed_later_keeps_the_answers_where_they_were(pharmacy, staff):
    cold, rx = topic(pharmacy), topic(pharmacy, "Retsept")
    answers(staff, cold, [1, 1, 1])
    Question.objects.update(topic=rx)
    assert (staff.pk, cold.pk) in skills.mastery(pharmacy)


def test_the_matrix_people_topics_and_averages(pharmacy, staff):
    cold, rx = topic(pharmacy), topic(pharmacy, "Retsept")
    madina = person(pharmacy, first_name="Madina", last_name="Saidova")
    answers(staff, cold, [0, 0, 1])  # 39: weak
    answers(madina, cold, [1, 1, 1])  # 100: strong
    answers(madina, rx, [1])  # unrated
    found = skills.matrix(pharmacy, branch_ids=None)
    names = [str(row["member"]) for row in found["people"]]
    assert names == ["Alisher Valiyev", "Madina Saidova"]
    columns = {column["topic"].name: column for column in found["topics"]}
    assert (columns["Sovuq zanjir"]["average"], columns["Sovuq zanjir"]["rated"]) == (70, 2)
    assert (columns["Sovuq zanjir"]["weak"], columns["Sovuq zanjir"]["strong"]) == (1, 1)
    assert columns["Retsept"]["average"] is None
    madina_row = found["people"][1]
    assert madina_row["cells"][rx.pk] == {
        "score": None,
        "answers": 1,
        "band": "unrated",
        "last_at": madina_row["cells"][rx.pk]["last_at"],
    }
    weakest_first = skills.matrix(pharmacy, branch_ids=None, sort_topic=cold.pk)
    assert str(weakest_first["people"][0]["member"]) == "Alisher Valiyev"


def test_the_matrix_keeps_to_the_viewers_branches_and_a_position(pharmacy, staff):
    cold = topic(pharmacy)
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    night = person(pharmacy, branch=yunusobod, first_name="Nigora", last_name="Azimova")
    answers(staff, cold, [1, 1, 1])
    answers(night, cold, [0, 0, 0])
    viewer = branch_viewer(pharmacy, [yunusobod])
    seen = skills.matrix(pharmacy, branch_ids=[yunusobod.pk])
    assert {row["member"].pk for row in seen["people"]} == {night.pk, viewer.pk}
    assert seen["topics"][0]["average"] == 0
    pharmacists = position(pharmacy)
    night.position = pharmacists
    night.save()
    only = skills.matrix(pharmacy, branch_ids=None, position_id=pharmacists.pk)
    assert [row["member"].pk for row in only["people"]] == [night.pk]


def test_weakest_topics_and_a_persons_skills(pharmacy, staff):
    cold, rx, till = topic(pharmacy), topic(pharmacy, "Retsept"), topic(pharmacy, "Kassa")
    answers(staff, cold, [1, 1, 1])
    answers(staff, rx, [0, 0, 1])
    answers(staff, till, [1])
    assert [row["topic"].name for row in skills.weakest_topics(pharmacy, branch_ids=None)] == [
        "Retsept",
        "Sovuq zanjir",
    ]
    assert [row["topic"].name for row in skills.of_person(staff)] == [
        "Retsept",
        "Sovuq zanjir",
        "Kassa",
    ]
