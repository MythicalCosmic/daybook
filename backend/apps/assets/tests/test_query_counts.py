"""The asset reports read every asset's events, posted months, photo and branch with the list:
a page costs the same number of queries however many assets the company owns."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.assets import services

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/assets"


def queries_of(client, url: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        answer = client.get(url)
    assert answer.status_code == 200, answer.content
    return len(queries)


def test_reports_do_not_grow_with_the_assets(shop, owner, ali, owner_api, category, chilonzor):
    client = owner_api(owner)
    urls = [
        f"{base(shop)}/summary/",
        f"{base(shop)}/depreciation/?year=2026&group=category",
        f"{base(shop)}/planning/",
        f"{base(shop)}/custody/",
    ]

    def fridge(number: int, holder) -> None:
        """A fridge in service since September, out with `holder`."""
        asset = services.create_asset(
            shop,
            by=owner,
            category=category,
            name=f"Muzlatgich {number}",
            cost=D(8_400_000),
            life_months=84,
            branch=chilonzor,
            in_service_on=date(2026, 9, 10),
        )
        services.issue(asset, by=owner, membership=holder, on=date(2026, 11, 7))

    fridge(0, ali)
    for url in urls:  # the first call of a page also makes its settings rows
        queries_of(client, url)
    few = {url: queries_of(client, url) for url in urls}
    for number in range(1, 5):
        fridge(number, ali if number % 2 else owner)
    many = {url: queries_of(client, url) for url in urls}
    custody = client.get(urls[3]).json()
    assert sorted(len(person["assets"]) for person in custody) == [2, 3]
    assert client.get(urls[0]).json()["count"] == 5
    # One more person holds assets now: nothing else may differ.
    assert many == few
