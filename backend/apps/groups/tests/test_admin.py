import pytest

from apps.groups.models import GroupEvent
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db


def test_the_admin_edits_a_groups_events(admin_client, company):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.LATE])

    response = admin_client.post(
        f"/admin/groups/telegramgroup/{group.pk}/change/",
        {"company": company.pk, "title": "Shop team", "events": ["morning", "evening"]},
    )

    assert response.status_code == 302
    group.refresh_from_db()
    assert group.events == [GroupEvent.MORNING, GroupEvent.EVENING]
    assert not group.is_active  # an unticked box


def test_the_admin_refuses_another_companys_positions(admin_client, company, other_company):
    group = TelegramGroupFactory(company=company)
    foreign = PositionFactory(company=other_company)

    response = admin_client.post(
        f"/admin/groups/telegramgroup/{group.pk}/change/",
        {"company": company.pk, "events": ["late"], "positions": [foreign.pk], "is_active": "on"},
    )

    assert response.status_code == 200  # the form comes back with an error
    assert not group.positions.exists()
