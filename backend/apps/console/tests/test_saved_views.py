"""`saved-views/`: your own views, colleagues' shared ones, overview layouts."""

import pytest

from apps.audit.models import AuditLog
from apps.console.models import SavedView
from apps.console.tests.factories import SavedViewFactory

pytestmark = pytest.mark.django_db


def views_url(company, pk=None) -> str:
    base = f"/api/v1/owner/companies/{company.pk}/saved-views/"
    return f"{base}{pk}/" if pk else base


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


@pytest.fixture
def manager(company, member):
    return member(company, "Manager")


def test_create_a_view(company, owner, owner_api):
    response = owner_api(owner).post(
        views_url(company),
        {"module": "tasks", "name": "Late today", "state": {"filters": {"overdue": True}}},
        format="json",
    )

    assert response.status_code == 201
    view = SavedView.objects.get()
    assert (view.membership, view.company, view.is_shared) == (owner, company, False)
    assert response.data["is_mine"] is True
    assert response.data["owner"] == {"id": owner.pk, "name": str(owner)}
    assert not AuditLog.objects.exists()  # a personal preference, not company data


def test_the_overview_layout_is_a_saved_view(company, owner, owner_api):
    layout = {"widgets": [{"id": "sales.today", "hidden": False, "order": 1, "span": 2}]}

    response = owner_api(owner).post(
        views_url(company), {"module": "overview", "name": "layout", "state": layout}, format="json"
    )

    assert response.status_code == 201
    assert (
        owner_api(owner).get(views_url(company), {"module": "overview"}).data[0]["state"] == layout
    )


def test_list_shows_mine_and_shared_ones_of_this_company(
    company, other_company, owner, manager, member, owner_api
):
    mine = SavedViewFactory(membership=owner, name="Mine")
    shared = SavedViewFactory(membership=manager, name="Team", is_shared=True)
    SavedViewFactory(membership=manager, name="Private")
    SavedViewFactory(membership=member(other_company, "Owner"), is_shared=True)
    SavedViewFactory(membership=owner, module="finance", name="Money")

    response = owner_api(owner).get(views_url(company), {"module": "tasks"})

    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {mine.pk, shared.pk}
    assert {row["id"]: row["is_mine"] for row in response.data} == {mine.pk: True, shared.pk: False}


def test_sharing_is_audited(company, owner, owner_api):
    view = SavedViewFactory(membership=owner)

    response = owner_api(owner).patch(
        views_url(company, view.pk), {"is_shared": True}, format="json"
    )

    assert response.status_code == 200
    assert AuditLog.objects.get().action == "console.saved_view_shared"
    owner_api(owner).patch(views_url(company, view.pk), {"name": "Renamed"}, format="json")
    owner_api(owner).delete(views_url(company, view.pk))
    assert list(AuditLog.objects.order_by("created_at").values_list("action", flat=True)) == [
        "console.saved_view_shared",
        "console.saved_view_changed",
        "console.saved_view_deleted",
    ]


def test_a_colleagues_shared_view_can_be_read_but_not_changed(company, owner, manager, owner_api):
    shared = SavedViewFactory(membership=manager, is_shared=True)

    client = owner_api(owner)
    assert client.get(views_url(company, shared.pk)).status_code == 200
    assert (
        client.patch(views_url(company, shared.pk), {"name": "Mine now"}, format="json").status_code
        == 404
    )
    assert client.delete(views_url(company, shared.pk)).status_code == 404
    assert SavedView.objects.filter(pk=shared.pk, name=shared.name).exists()


def test_names_are_unique_per_person_and_module(company, owner, owner_api):
    SavedViewFactory(membership=owner, name="Late")

    response = owner_api(owner).post(
        views_url(company), {"module": "tasks", "name": "Late", "state": {}}, format="json"
    )

    assert response.status_code == 400


def test_state_must_be_a_small_object(company, owner, owner_api):
    client = owner_api(owner)

    assert (
        client.post(
            views_url(company), {"module": "tasks", "name": "A", "state": [1, 2]}, format="json"
        ).status_code
        == 400
    )
    huge = {"filters": "x" * 40_000}
    assert (
        client.post(
            views_url(company), {"module": "tasks", "name": "B", "state": huge}, format="json"
        ).status_code
        == 400
    )


def test_saved_views_are_company_scoped(company, other_company, member, owner_api):
    outsider = member(other_company, "Owner")
    employee = member(company)
    view = SavedViewFactory(membership=member(company, "Owner"), is_shared=True)

    assert owner_api(outsider).get(views_url(company)).status_code == 404
    assert owner_api(outsider).get(views_url(company, view.pk)).status_code == 404
    assert owner_api(employee).get(views_url(company)).status_code == 403
    # Another company's id in the URL never reaches this company's views.
    assert owner_api(outsider).get(views_url(other_company, view.pk)).status_code == 404
