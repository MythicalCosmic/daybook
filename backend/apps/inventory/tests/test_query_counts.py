"""The stock lists read their rows' people and products with the list, not row by row: a page
costs the same number of queries however many rows it shows."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.inventory import services
from apps.inventory.tests.conftest import DAY, D, line, opening, receive

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/stock"


def queries_of(client, url: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        answer = client.get(url)
    assert answer.status_code == 200, answer.content
    return len(queries)


def test_documents_lists_do_not_grow_with_their_rows(
    shop, owner, ali, owner_api, chilonzor, yunusobod, supplier, product
):
    client = owner_api(owner)
    urls = [
        f"{base(shop)}/movements/",
        f"{base(shop)}/products/{product.pk}/movements/",
        f"{base(shop)}/receipts/",
        f"{base(shop)}/transfers/",
        f"{base(shop)}/write-offs/",
        f"{base(shop)}/defektura/",
    ]

    def documents(number: int, by) -> None:
        """A receipt, a transfer, a write-off and a request, each with its own people."""
        series = f"S{number}"
        receive(
            shop, by, chilonzor, supplier, [line(product, series, packs=5)], invoice=f"N-{number}"
        )
        batch = product.batches.get(series=series)
        transfer = services.create_transfer(
            shop,
            by=by,
            from_branch=chilonzor,
            to_branch=yunusobod,
            lines=[{"product": product, "batch": batch, "quantity": D(2)}],
        )
        services.send_transfer(transfer, by=by)
        services.propose_writeoff(
            shop,
            by=by,
            branch=chilonzor,
            reason="damaged",
            lines=[{"batch": batch, "quantity": 1}],
        )
        services.add_request(chilonzor, by=by, name=f"Insulin {number}")

    documents(0, owner)
    for url in urls:  # the first call of a page also makes its settings rows
        queries_of(client, url)
    few = {url: queries_of(client, url) for url in urls}
    for number in range(1, 5):
        documents(number, ali if number % 2 else owner)
    many = {url: queries_of(client, url) for url in urls}
    assert len(client.get(urls[0]).json()) >= 10
    assert many == few


def test_a_counts_page_does_not_grow_with_its_lines(
    shop, owner, owner_api, chilonzor, yunusobod, product
):
    client = owner_api(owner)
    opening(chilonzor, product, "C1", expires_on=DAY.replace(year=2028), quantity=10)
    for number in range(6):
        opening(yunusobod, product, f"Y{number}", expires_on=DAY.replace(year=2028), quantity=10)
    counts, listed = {}, []
    for branch in (chilonzor, yunusobod):
        count = services.start_count(branch, by=owner)
        for row in count.lines.all():
            row.counted = D(9)
            row.save(update_fields=["counted"])
        assert client.post(f"{base(shop)}/counts/{count.pk}/submit/").status_code == 200
        counts[branch.name] = count
        queries_of(client, f"{base(shop)}/counts/")
        listed.append(queries_of(client, f"{base(shop)}/counts/"))
    # The list names who started each count: one count or two, the same queries.
    assert listed[0] == listed[1]
    one, six = counts["Chilonzor"], counts["Yunusobod"]
    small = queries_of(client, f"{base(shop)}/counts/{one.pk}/")
    large = client.get(f"{base(shop)}/counts/{six.pk}/").json()
    # Reviewed with costs: every line prices its difference through its batch's product.
    assert len(large["lines"]) == 6 and large["lines"][0]["value_difference"] is not None
    assert queries_of(client, f"{base(shop)}/counts/{six.pk}/") == small
