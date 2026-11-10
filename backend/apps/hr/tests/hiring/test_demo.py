"""Demo Dorixona's hiring: two open vacancies (Farmatsevt at Chilonzor, Kassir at Yunusobod) with
applicants at every stage, a closed one Kamola was hired through, and a draft."""

import pytest
from django.utils import timezone

from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import EVERYONE, OLD_PEOPLE, Command
from apps.hr.hiring import demo, queries, services
from apps.hr.models import Applicant
from apps.hr.tests.conftest import DAY, local
from apps.members import demo as members_demo
from apps.members.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(freeze):
    freeze(local(DAY, 10, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    members_demo.seed(company, people, now)
    demo.seed(company, people, now)
    return company, people


def test_the_story_of_the_demo(pharmacy):
    company, people = pharmacy
    rows = {
        (vacancy.title, vacancy.branch.name, vacancy.status): vacancy
        for vacancy in queries.with_counts(queries.vacancies(company, branch_ids=None))
    }
    assert set(rows) == {
        ("Farmatsevt", "Chilonzor", "open"),
        ("Kassir", "Yunusobod", "open"),
        ("Farmatsevt", "Yunusobod", "closed"),
        ("Kuryer (velosipedda)", "Chilonzor", "draft"),
    }
    chilonzor = rows["Farmatsevt", "Chilonzor", "open"]
    kassir = rows["Kassir", "Yunusobod", "open"]
    closed = rows["Farmatsevt", "Yunusobod", "closed"]
    draft = rows["Kuryer (velosipedda)", "Chilonzor", "draft"]

    assert chilonzor.asks_document and chilonzor.closes_on is not None
    assert (
        chilonzor.count_new,
        chilonzor.count_screening,
        chilonzor.count_interview,
        chilonzor.count_offer,
        chilonzor.count_rejected,
    ) == (2, 1, 1, 1, 1)
    assert (kassir.count_new, kassir.count_screening, kassir.count_interview) == (1, 1, 1)
    assert kassir.position.role.name == "Cashier"
    assert (closed.count_hired, closed.count_rejected) == (1, 1)
    assert draft.count_total == 0

    # Kamola got the job she has: her application is linked to her membership.
    hired = Applicant.objects.get(vacancy=closed, stage="hired")
    assert hired.membership.user.telegram_id == 3006 and hired.name == "Kamola Ergasheva"
    assert [event.to_stage for event in hired.events.all()] == [
        "new",
        "screening",
        "interview",
        "offer",
        "hired",
    ]
    # Weeks of history: everything happened before now, in order, by the branch heads.
    for applicant in Applicant.objects.filter(company=company):
        moments = [event.created_at for event in applicant.events.all()]
        assert moments == sorted(moments) and moments[-1] <= timezone.now()
    offered = Applicant.objects.get(vacancy=chilonzor, stage="offer")
    assert offered.document and offered.language == "ru"
    assert offered.events.filter(kind="note").exists()
    assert {e.by for e in offered.events.exclude(by=None)} == {people["manager"]}
    # The applicants' accounts are cleaned up by --reset (and none of them is a member).
    first, last = OLD_PEOPLE
    for applicant in Applicant.objects.filter(company=company).exclude(pk=hired.pk):
        telegram_id = applicant.user.telegram_id
        assert telegram_id in EVERYONE or first <= telegram_id <= last
        assert not Membership.objects.filter(user=applicant.user).exists()
    # Farrux runs Yunusobod's hiring but can't give the cashier's access: the owner hires.
    farrux = Membership.objects.get(company=company, user__telegram_id=3007)
    assert "Ask an owner" in services.hire_blocker(farrux, kassir)
    assert services.hire_blocker(people["owner"], kassir) is None
    assert services.hire_blocker(people["manager"], chilonzor) is None
    assert queries.new_count(people["manager"]) == 2  # Chilonzor's new ones only
