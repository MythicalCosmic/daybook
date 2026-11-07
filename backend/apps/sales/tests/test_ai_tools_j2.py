"""The AI tools of sale lines, customer debts and invoices (§14.12): read-only, in the asker's
company and branches, money as strings."""

from datetime import date
from decimal import Decimal

from apps.ai.tools.registry import ToolContext
from apps.sales import ai_tools, lines, services
from apps.sales.models import SalesSettings
from apps.sales.tests.test_lines import AMOXICILLIN, COLUMNS, csv_file, line


def test_top_lines_customer_debts_and_invoices(shop):
    from apps.inventory.tests.factories import ProductFactory

    SalesSettings.objects.filter(company=shop.company).update(sales_lines="import")
    ProductFactory(
        company=shop.company,
        barcode=AMOXICILLIN,
        units_per_pack=1,
        rx_required=True,
        reference_price=Decimal("12000.00"),
    )
    profile = services.create_import_profile(
        shop.company, by=shop.owner, name="Kassa", columns=COLUMNS, branch=shop.branch
    )
    imp = services.start_import(
        profile,
        by=shop.owner,
        file=csv_file(
            line(receipt="1", code=AMOXICILLIN, total="15000"),
            line(receipt="2", code=AMOXICILLIN, quantity="2", total="24000"),
        ),
    )
    lines.process(imp.pk)
    ctx = ToolContext.for_member(shop.owner)
    day = date(2026, 10, 21)
    top = ai_tools.sales_lines_top(ctx, ai_tools.TopInput(start=day, end=day))
    [row] = top.rows
    assert row["packs"] == "3.00" and row["total"] == "39000.00" and row["lines"] == 2
    assert top.data == {"cap_breaches": 1}

    customer = services.create_customer(shop.company, by=shop.owner, name="Shifo", kind="clinic")
    invoice = services.create_invoice(
        shop.company,
        by=shop.owner,
        counterparty=customer,
        lines=[{"name": "Analysis", "quantity": 1, "price": 80000}],
        branch=shop.branch,
    )
    invoice = services.issue_invoice(invoice, by=shop.owner)
    debts = ai_tools.sales_customer_debts(ctx, ai_tools.EmptyInput())
    assert debts.data["total"] == "80000.00" and debts.rows[0]["name"] == "Shifo"
    issued = invoice.issued_on
    found = ai_tools.sales_invoices(ctx, ai_tools.InvoicesInput(start=issued, end=issued))
    assert [row["number"] for row in found.rows] == ["INV-CHL-0001"]
    # Another branch's lead sees none of it.
    from apps.members.permissions import Perm
    from apps.sales.tests.factories import make_member, scoped_role

    lead = make_member(shop.company, "Owner", branches=(shop.other_branch,))
    lead.role = scoped_role(shop.company, Perm.SALES_VIEW)
    lead.save(update_fields=["role"])
    theirs = ToolContext.for_member(lead)
    assert ai_tools.sales_lines_top(theirs, ai_tools.TopInput(start=day, end=day)).rows == []
    assert (
        ai_tools.sales_invoices(theirs, ai_tools.InvoicesInput(start=issued, end=issued)).rows == []
    )
