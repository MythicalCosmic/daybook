"""`tasks.queries.routines` / `routine`: how other apps (knowledge's "How to do this") read the
company's routines without touching TaskTemplate themselves."""

import pytest

from apps.tasks import queries
from apps.tasks.tests.factories import TaskTemplateFactory

pytestmark = pytest.mark.django_db


def test_routines_are_the_companys_shared_ones_by_title(company, other_company):
    close = TaskTemplateFactory(company=company, title="Close the till")
    open_ = TaskTemplateFactory(company=company, title="Open the till")
    paused = TaskTemplateFactory(company=company, title="Count the safe", is_active=False)
    welcome = TaskTemplateFactory(company=company, title="Read the rules", onboarding=True)
    TaskTemplateFactory(company=company, title="My own gym", personal=True)
    TaskTemplateFactory(company=other_company, title="Their till")

    assert list(queries.routines(company.pk)) == [close, paused, open_, welcome]
    assert list(queries.routines(company.pk, q=" till ")) == [close, open_]
    assert list(queries.routines(company.pk, active=True)) == [close, open_, welcome]
    assert list(queries.routines(company.pk, active=False)) == [paused]


def test_one_routine_only_from_the_company_and_never_a_personal_one(company, other_company):
    mine = TaskTemplateFactory(company=company, title="Close the till")
    personal = TaskTemplateFactory(company=company, title="My own gym", personal=True)
    theirs = TaskTemplateFactory(company=other_company, title="Their till")

    assert queries.routine(company.pk, mine.pk) == mine
    assert queries.routine(company.pk, str(mine.pk)) == mine
    assert queries.routine(company.pk, personal.pk) is None
    assert queries.routine(company.pk, theirs.pk) is None
    assert queries.routine(company.pk, "nope") is None
    assert queries.routine(company.pk, None) is None
