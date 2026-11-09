"""Fixtures and builders of package Q2's tests (quizzes, the daily question, checks, the tutor).

`conftest.py` next to this file makes the fixtures available to the tests of this folder; the
builders (`question`, `quiz`, `person`, ...) are imported by the tests, the bot's included.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Feature
from apps.companies.tests.factories import CompanyFactory
from apps.knowledge.models import Topic
from apps.learning.models import Question, Quiz, QuizQuestion, Status
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import MembershipFactory, PositionFactory

TASHKENT = ZoneInfo("Asia/Tashkent")

DATA = {
    "single": {
        "options": [
            {"id": "a", "text": "+2 dan +8 gacha", "correct": True},
            {"id": "b", "text": "0 dan +4 gacha", "correct": False},
            {"id": "c", "text": "+15 dan +25 gacha", "correct": False},
        ]
    },
    "multi": {
        "options": [
            {"id": "a", "text": "Insulin", "correct": True},
            {"id": "b", "text": "Paratsetamol", "correct": False},
            {"id": "c", "text": "Vaksina", "correct": True},
        ]
    },
    "true_false": {"answer": False},
    "order": {
        "items": [
            {"id": "a", "text": "Sanash"},
            {"id": "b", "text": "Tekshirish"},
            {"id": "c", "text": "Joylash"},
        ]
    },
    "match": {
        "pairs": [
            {"id": "a", "left": "XPN", "right": "Ta’sir etuvchi modda"},
            {"id": "b", "left": "Defektura", "right": "Topilmagan dori"},
        ]
    },
    "text": {"answers": ["muzlatgich"], "case": False},
    "number": {"value": 37.25, "tolerance": 0, "unit": "ml"},
}


def local(*args) -> datetime:
    """A moment in Tashkent time (the test companies' zone)."""
    return datetime(*args, tzinfo=TASHKENT)


def switch_on(company, *features: str):
    company.features = sorted({*company.features, Feature.LEARNING, *features})
    company.save(update_fields=["features"])
    return company


@pytest.fixture
def freeze(monkeypatch):
    """`freeze(moment)`: `timezone.now()` returns `moment` from then on."""

    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def pharmacy(db):
    """A company with learning on (workdays Monday to Saturday, Tashkent)."""
    return switch_on(CompanyFactory(name="Shifo Dorixona", workdays=[0, 1, 2, 3, 4, 5]))


def role(company, name: str) -> AccessRole:
    return AccessRole.objects.get(company=company, name=name)


def person(company, role_name="Employee", *, branch=None, position=None, **kwargs) -> Membership:
    kwargs.setdefault("status", Membership.Status.APPROVED)
    member = MembershipFactory(
        company=company, role=role(company, role_name), position=position, **kwargs
    )
    branch = branch or company.branches.order_by("pk").first()
    if branch is not None:
        member.branches.add(branch)
        if member.home_branch_id is None:
            member.home_branch = branch
            member.save(update_fields=["home_branch"])
    return member


@pytest.fixture
def manager(pharmacy):
    """Holds learning.manage (the Manager role: every branch)."""
    return person(pharmacy, "Manager", first_name="Bekzod", last_name="Mirzayev")


@pytest.fixture
def staff(pharmacy):
    return person(pharmacy, first_name="Alisher", last_name="Valiyev")


def branch_viewer(company, branches, *, perms=(Perm.LEARNING_VIEW,)) -> Membership:
    """Someone with dashboard access who sees only `branches`."""
    custom = AccessRole.objects.create(
        company=company,
        name=f"Viewer {AccessRole.objects.count()}",
        permissions=[Perm.DASHBOARD_ACCESS, *perms],
    )
    member = MembershipFactory(
        company=company, role=custom, status=Membership.Status.APPROVED, home_branch=branches[0]
    )
    member.branches.set(branches)
    return member


def topic(company, name="Sovuq zanjir") -> Topic:
    found = Topic.objects.filter(company=company, name=name).first()
    return found or Topic.objects.create(company=company, name=name, color="sky")


def question(company, kind="single", *, topic=None, **fields) -> Question:
    fields.setdefault("text", f"{kind} question?")
    fields.setdefault("data", DATA[kind])
    return Question.objects.create(company=company, kind=kind, topic=topic, **fields)


def quiz(company, questions=(), **fields) -> Quiz:
    fields.setdefault("title", "Sovuq zanjir testi")
    fields.setdefault("status", Status.PUBLISHED)
    fields.setdefault("shuffle_questions", False)
    found = Quiz.objects.create(company=company, **fields)
    for index, item in enumerate(questions):
        QuizQuestion.objects.create(company=company, quiz=found, question=item, position=index)
    return found


def position(company, name="Farmatsevt"):
    return PositionFactory(company=company, name=name)
