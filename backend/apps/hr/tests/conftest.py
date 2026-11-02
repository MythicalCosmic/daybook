"""Fixtures of the HR tests: a pharmacy with two branches (Chilonzor and Yunusobod) and the HR
module on, and its people by what they may do:

- owner: every permission (hr.sensitive included);
- manager: the Manager role (hr.view, no hr.manage), every branch;
- accountant: the Accountant role (hr.view and hr.manage, no hr.sensitive), every branch;
- lead: hr.view and hr.manage at Chilonzor only (no branches.all);
- ali, vali: pharmacists at Chilonzor; sara: a pharmacist at Yunusobod (no permissions).

The reference day is Wednesday 21 October 2026, Asia/Tashkent; `freeze` pins the clock.
"""

from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.companies.models import Branch
from apps.members.models import AccessRole, Position
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 10, 21)
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def local(day: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def pdf_upload(name: str = "scan.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


@pytest.fixture
def freeze(monkeypatch):
    """`freeze(moment)`: `timezone.now()` returns `moment` from then on."""

    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def shop(company, freeze):
    freeze(local(DAY, 10))
    company.features = ["hr", "payroll", "attendance"]
    company.save(update_fields=["features"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    return company


@pytest.fixture
def chilonzor(shop):
    return shop.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(shop):
    return shop.branches.get(name="Yunusobod")


@pytest.fixture
def staff(shop, member, chilonzor, yunusobod):
    pharmacist = Position.objects.create(company=shop, name="Pharmacist", order=1)
    office = Position.objects.create(company=shop, name="Office", order=2)
    AccessRole.objects.create(
        company=shop,
        name="Branch HR",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.HR_VIEW, Perm.HR_MANAGE],
    )

    def make(role="Employee", branch=chilonzor, position=pharmacist, **kwargs):
        made = member.registered(shop, role, position=position, home_branch=branch, **kwargs)
        made.branches.add(branch)
        return made

    people = SimpleNamespace(
        owner=make("Owner", position=office, first_name="Dilnoza", last_name="Karimova"),
        manager=make("Manager", position=office, first_name="Bekzod", last_name="Mirzayev"),
        accountant=make("Accountant", position=office, first_name="Aziza", last_name="Rasulova"),
        lead=make("Branch HR", position=office, first_name="Lola", last_name="Qodirova"),
        ali=make(first_name="Ali", last_name="Valiyev"),
        vali=make(first_name="Vali", last_name="Aliyev"),
        sara=make(branch=yunusobod, first_name="Sara", last_name="Tosheva"),
        pharmacist=pharmacist,
        office=office,
    )
    for person in (people.owner, people.manager, people.accountant):
        person.branches.add(yunusobod)
    return people


@pytest.fixture
def outsider(other_company, member):
    """Someone of another company, with every permission there."""
    other_company.features = ["hr"]
    other_company.save(update_fields=["features"])
    person = member.registered(other_company, "Owner", first_name="Begona")
    person.branches.add(other_company.branches.first())
    return person
