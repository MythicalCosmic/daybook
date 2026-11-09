"""Ask AI's learning tools of package Q2: who may use them, branch scope, the shapes."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.tools import registry
from apps.ai.tools.registry import ToolContext
from apps.companies.tests.factories import BranchFactory
from apps.learning import attempts, checks
from apps.learning.models import AnswerLog, RegularCheck, TutorSuggestion
from apps.learning.tests.q2.fixtures import branch_viewer, person, question, quiz, topic

pytestmark = pytest.mark.django_db

NAMES = ("learning_checks", "learning_quiz_results", "learning_skills", "learning_suggestions")


def run(member, name, args=None):
    return registry.run_tool(name, ToolContext.for_member(member), args or {})


def answers(member, topic_row, shares):
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
            at=timezone.now() - timedelta(hours=index + 1),
        )


def test_the_tools_are_for_learning_viewers_where_learning_runs(pharmacy, manager, staff):
    for name in NAMES:
        tool = registry.get_tool(name)
        assert (tool.domain, str(tool.perm), tool.feature) == (
            "learning",
            "learning.view",
            "learning",
        )
        assert tool.allowed(ToolContext.for_member(manager))
        assert not tool.allowed(ToolContext.for_member(staff))
        assert run(staff, name) == {"error": "not_allowed"}
    pharmacy.features = [feature for feature in pharmacy.features if feature != "learning"]
    pharmacy.save(update_fields=["features"])
    manager.company.refresh_from_db()
    assert not registry.get_tool("learning_skills").allowed(ToolContext.for_member(manager))


def test_skills_weakest_people_first_within_the_askers_branches(pharmacy, manager, staff):
    cold = topic(pharmacy)
    madina = person(pharmacy, first_name="Madina", last_name="Saidova")
    yunusobod = BranchFactory(company=pharmacy, name="Yunusobod")
    nigora = person(pharmacy, branch=yunusobod, first_name="Nigora", last_name="Azimova")
    answers(staff, cold, [0, 0, 1])
    answers(madina, cold, [1, 1, 1])
    answers(nigora, cold, [0, 0, 0])
    found = run(manager, "learning_skills")
    assert [row["name"] for row in found["rows"]] == [
        "Nigora Azimova",
        "Alisher Valiyev",
        "Madina Saidova",
    ]
    assert found["rows"][0]["weak"] == ["Sovuq zanjir"]
    assert found["data"]["topics"][0]["name"] == "Sovuq zanjir"
    head = branch_viewer(pharmacy, [yunusobod])
    assert [row["name"] for row in run(head, "learning_skills")["rows"]] == ["Nigora Azimova"]


def test_quiz_results_suggestions_and_checks(pharmacy, manager, staff):
    test = quiz(pharmacy, [question(pharmacy, "true_false")], title="Retsept testi")
    attempt, _new = attempts.start(test, staff)
    attempts.finish(attempt)
    [row] = run(manager, "learning_quiz_results")["rows"]
    assert (row["title"], row["attempts"], row["pass_rate"]) == ("Retsept testi", 1, 0)
    TutorSuggestion.objects.create(
        company=pharmacy, membership=staff, kind="praise", params={"points": 40}
    )
    [suggestion] = run(manager, "learning_suggestions")["rows"]
    assert suggestion["text"] == "Alisher Valiyev earned 40 points this week: say thanks."
    check = checks.create_check(
        pharmacy, by=manager, title="Dushanba", quiz_id=test.pk, every="week", weekday=0
    )
    checks.start_round(RegularCheck.objects.get(pk=check.pk), timezone.now() - timedelta(hours=1))
    [found] = run(manager, "learning_checks")["rows"]
    assert found["title"] == "Dushanba" and found["latest"]["people"] == 2
    assert sorted(found["latest"]["not_answered"]) == ["Alisher Valiyev", "Bekzod Mirzayev"]
