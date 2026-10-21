"""Company holidays: the service (audited) and the owner endpoints."""

from datetime import date

import pytest

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.timeoff import services
from apps.timeoff.models import Holiday

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/holidays/"


def test_holidays_are_audited(company, member):
    owner = member.registered(company, "Owner")

    holiday = services.create_holiday(
        company, by=owner, date=date(2026, 12, 8), name="Constitution Day"
    )
    services.update_holiday(holiday, by=owner, name="Konstitutsiya kuni")
    services.delete_holiday(holiday, by=owner)

    actions = list(
        AuditLog.objects.filter(target_type="holiday")
        .order_by("pk")
        .values_list("action", flat=True)
    )
    assert actions == [
        "timeoff.holiday_added",
        "timeoff.holiday_changed",
        "timeoff.holiday_removed",
    ]


def test_one_holiday_per_day(company, member):
    owner = member.registered(company, "Owner")
    services.create_holiday(company, by=owner, date=date(2026, 3, 21), name="Navruz")

    with pytest.raises(DomainError):
        services.create_holiday(company, by=owner, date=date(2026, 3, 21), name="Again")


def test_public_holidays_are_added_once(owner_api, company, member):
    owner = member.registered(company, "Owner")
    Holiday.objects.create(company=company, date=date(2027, 1, 1), name="Yangi yil")
    url = URL.format(cid=company.pk) + "public/"

    first = owner_api(owner).post(url, {"year": 2027}, format="json")
    second = owner_api(owner).post(url, {"year": 2027}, format="json")

    assert first.status_code == 201
    assert len(first.data) == 6  # New Year was already there
    assert second.data == []
    assert Holiday.objects.filter(company=company, date__year=2027).count() == 7


def test_crud_endpoints(owner_api, company, other_company, member):
    owner = member.registered(company, "Owner")
    worker = member.registered(company)
    stranger = member.registered(other_company, "Owner")
    api = owner_api(owner)
    url = URL.format(cid=company.pk)

    created = api.post(url, {"date": "2026-10-01", "name": "Teachers' Day"}, format="json")
    assert created.status_code == 201
    listed = api.get(url, {"year": 2026})
    assert [row["name"] for row in listed.data] == ["Teachers' Day"]
    changed = api.patch(
        url + f"{created.data['id']}/", {"name": "O‘qituvchilar kuni"}, format="json"
    )
    assert changed.data["name"] == "O‘qituvchilar kuni"
    assert owner_api(worker).get(url).status_code == 403
    assert owner_api(stranger).get(url).status_code == 404
    assert api.delete(url + f"{created.data['id']}/").status_code == 204
