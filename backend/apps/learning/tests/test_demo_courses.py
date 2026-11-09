"""The training demo (docs/PLAN-LEARNING.md §14), through the root `demo_people` fixture, on top
of the knowledge base demo's pages and topics."""

import pytest
from django.utils import timezone

from apps.knowledge import demo as knowledge_demo
from apps.knowledge.models import PageView
from apps.learning import demo_courses, queries
from apps.learning.models import Assignment, Course, Lesson, LessonProgress, Status, Video
from apps.learning.tests.helpers_courses import HAS_FFMPEG, turn_on

pytestmark = pytest.mark.django_db


def test_the_demo_tells_the_story(company, demo_people):
    turn_on(company)
    people = demo_people(company)
    now = timezone.now()
    knowledge_demo.seed(company, people, now)

    demo_courses.seed(company, people, now)

    titles = set(Course.objects.filter(company=company).values_list("title", flat=True))
    assert titles == {
        "Yangi xodim kursi",
        "Sovuq zanjir",
        "Retsept bo‘yicha dori berish",
        "Kassa qoidalari",
    }
    assert Lesson.objects.filter(company=company).count() == 4
    mine = lambda key, title: Assignment.objects.get(  # noqa: E731
        membership=people[key], course__title=title
    )
    # Jasur (courier) finished the new-hire course, like everyone (the owner wrote its pages).
    assert mine("jasur", "Yangi xodim kursi").state == Assignment.State.COMPLETED
    assert mine("owner", "Yangi xodim kursi").state == Assignment.State.COMPLETED
    assert not Assignment.objects.filter(membership=people["jasur"], course__title="Sovuq zanjir")
    assert PageView.objects.filter(company=company).count() >= 10
    if not HAS_FFMPEG:
        # Without ffmpeg the lessons stay drafts and nobody can watch them.
        assert not Lesson.objects.filter(company=company, status=Status.PUBLISHED).exists()
        return
    assert Video.objects.filter(company=company, state=Video.State.READY).count() == 4
    assert Lesson.objects.filter(company=company, status=Status.PUBLISHED).count() == 4
    # Madina finished every course, each with a certificate.
    madina = Assignment.objects.filter(membership=people["madina"])
    assert madina.count() == 4
    assert all(row.state == Assignment.State.COMPLETED and row.certificate_no for row in madina)
    # Alisher is late with the cold chain, a third of its video watched.
    late = mine("worker", "Sovuq zanjir")
    assert late.state == Assignment.State.IN_PROGRESS and queries.is_late(late, now)
    watched = LessonProgress.objects.get(
        membership=people["worker"], lesson__title="Sovuq zanjir: muzlatgich va termometr"
    )
    assert watched.percent == 30 and watched.completed_at is None
    # Nigora is half-way through prescriptions (the controlled register is optional).
    halfway = mine("nigora", "Retsept bo‘yicha dori berish")
    assert (halfway.steps_done, halfway.steps_total) == (1, 2)
    report = queries.compliance(company, branch_ids=None, now=now)
    assert report.overdue_people == 1 and report.late[0].membership_id == people["worker"].pk
