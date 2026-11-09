"""The training AI tools through `call_tool` (what the runtime sends): the module switch,
learning.view, branch scope, another company's ids, names only."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.companies.models import Branch
from apps.learning import courses
from apps.learning.models import Assignment, LessonProgress
from apps.learning.tests.factories import CourseFactory, CourseStepFactory, LessonFactory
from apps.learning.tests.helpers_courses import manager, turn_on

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(company, member):
    turn_on(company, "ai")
    north = company.branches.first()
    south = Branch.objects.create(company=company, name="Yunusobod")
    boss = manager(company, member)
    lead = manager(company, member, branches=[north])
    here = member(company, first_name="Alisher")
    there = member(company, first_name="Nigora")
    here.branches.set([north])
    there.branches.set([south])
    course = CourseFactory(company=company, mandatory=True, title="Sovuq zanjir")
    step = CourseStepFactory(course=course)
    rows = courses.assign(course, [here, there], by=None)
    Assignment.objects.filter(pk__in=[row.pk for row in rows]).update(
        due_at=timezone.now() - timedelta(days=4)
    )
    LessonProgress.objects.create(
        company=company,
        lesson=step.lesson,
        membership=there,
        percent=40,
        ranges=[[0, 120]],
        first_at=timezone.now(),
        last_at=timezone.now(),
    )
    return {
        "boss": boss,
        "lead": lead,
        "here": here,
        "there": there,
        "course": course,
        "step": step,
    }


def test_courses_and_who_is_late_in_scope(setup):
    answer = call_tool("learning_courses", setup["boss"])
    [row] = answer["rows"]
    assert (row["title"], row["people"], row["overdue"]) == ("Sovuq zanjir", 2, 2)
    assert {item["name"] for item in answer["data"]["late"]} == {
        str(setup["here"]),
        str(setup["there"]),
    }
    scoped = call_tool("learning_courses", setup["lead"])
    assert scoped["rows"][0]["people"] == 1
    assert [item["name"] for item in scoped["data"]["late"]] == [str(setup["here"])]


def test_a_course_and_a_lesson_by_id(setup, other_company):
    people = call_tool("learning_course_people", setup["lead"], course_id=setup["course"].pk)
    assert [row["name"] for row in people["rows"]] == [str(setup["here"])]
    assert "phone" not in str(people)
    viewers = call_tool("learning_lesson_viewers", setup["boss"], lesson_id=setup["step"].lesson_id)
    states = {row["name"]: row["state"] for row in viewers["rows"]}
    assert states[str(setup["there"])] == "watching" and states[str(setup["here"])] == "never"
    theirs = LessonFactory(company=other_company)
    assert call_tool("learning_lesson_viewers", setup["boss"], lesson_id=theirs.pk) == {
        "error": "not_found"
    }


def test_one_person_only_in_scope(setup):
    found = call_tool("learning_person", setup["boss"], member_id=setup["there"].pk)
    assert found["data"]["name"] == str(setup["there"])
    assert found["rows"][0]["course"] == "Sovuq zanjir"
    assert call_tool("learning_person", setup["lead"], member_id=setup["there"].pk) == {
        "error": "not_found"
    }


def test_the_tools_need_the_module(company, member):
    turn_on(company, "ai")
    boss = manager(company, member)
    company.features = ["ai"]
    company.save()
    assert "error" in call_tool("learning_courses", boss)
