"""The pay setup lists read each row's person and author with the list: a page costs the same
number of queries however many people it shows."""

from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.payroll import services

pytestmark = pytest.mark.django_db


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/payroll/{path}"


def queries_of(client, path: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        answer = client.get(path)
    assert answer.status_code == 200, answer.content
    return len(queries)


def test_pay_setup_lists_do_not_grow_with_the_people(shop, staff, owner_api, today):
    client = owner_api(staff.owner)
    urls = [url(shop, "compensations/"), url(shop, "compensations/people/")]

    def pay(person, by) -> None:
        """A setup in force and a raise planned, each written by `by`."""
        services.set_pay(person, by=by, effective_from=date(2026, 1, 1), amount=100)
        services.set_pay(person, by=by, effective_from=date(2026, 12, 1), amount=200)

    pay(staff.ali, staff.owner)
    for path in urls:  # the first call of a page also makes its settings rows
        queries_of(client, path)
    few = {path: queries_of(client, path) for path in urls}
    pay(staff.vali, staff.accountant)
    pay(staff.sara, staff.owner)
    pay(staff.lead, staff.accountant)
    many = {path: queries_of(client, path) for path in urls}
    rows = client.get(urls[1]).data["results"]
    assert sum(1 for row in rows if row["current"] and row["next"]) == 4
    assert many == few
