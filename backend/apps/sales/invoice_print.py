"""What the invoice PDF prints (`sales/invoice.html`, §14.7): the company and the customer, each
line with its MXIK code, VAT rate and the VAT it includes, the batch's series and expiry, the
totals, and the footer saying this is not the electronic invoice (EHF): the legal B2B document
is the e-invoice the company issues in its operator account (§14.4)."""

from decimal import ROUND_HALF_UP, Decimal

from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.money import format_money
from apps.core.pdf import image_src

CENT = Decimal("0.01")


def _money(amount, currency: str) -> str:
    language = (translation.get_language() or "uz")[:2]
    return format_money(amount or Decimal(0), currency, language)


def _vat(total: Decimal, rate: Decimal | None) -> Decimal:
    """The VAT a line's total includes at `rate` percent."""
    if not rate:
        return Decimal(0)
    return (total * rate / (100 + rate)).quantize(CENT, rounding=ROUND_HALF_UP)


def _quantity(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def context(invoice) -> dict:
    from apps.sales.conf import get_settings

    company = invoice.company
    currency = invoice.currency
    party = invoice.counterparty
    settings = get_settings(company)
    rows = []
    vat_total = Decimal(0)
    for line in invoice.lines.select_related("product").order_by("line_number", "pk"):
        vat = _vat(line.total, line.vat_percent)
        vat_total += vat
        rows.append(
            {
                "number": line.line_number,
                "name": line.name,
                "mxik": line.mxik_code or (line.product.mxik_code if line.product_id else ""),
                "series": line.series,
                "expires_on": line.expires_on.strftime("%d.%m.%Y") if line.expires_on else "",
                "quantity": _quantity(line.quantity),
                "price": _money(line.price, currency),
                "discount": _money(line.discount, currency) if line.discount else "",
                "total": _money(line.total, currency),
                "vat_percent": f"{line.vat_percent.normalize():f}" if line.vat_percent else "0",
                "vat": _money(vat, currency),
            }
        )
    title = (
        _("Invoice %(number)s") % {"number": invoice.number}
        if invoice.number
        else _("Draft invoice")
    )
    return {
        "company": company,
        "logo_src": image_src(company.logo) if getattr(company, "logo", None) else "",
        "title": title,
        "invoice": invoice,
        "issued_on": invoice.issued_on.strftime("%d.%m.%Y") if invoice.issued_on else "",
        "due_on": invoice.due_on.strftime("%d.%m.%Y") if invoice.due_on else "",
        "branch": invoice.branch.name if invoice.branch_id else "",
        "customer": {
            "name": party.name,
            "tin": party.tin,
            "address": party.address,
            "phone": party.phone,
            "contact": party.contact_person,
            "bank": party.bank_details,
        },
        "lines": rows,
        "subtotal": _money(invoice.subtotal, currency),
        "discount": _money(invoice.discount, currency) if invoice.discount else "",
        "total": _money(invoice.total, currency),
        "vat_total": _money(vat_total, currency),
        "notes": invoice.notes,
        "footer": settings.invoice_footer,
        "e_invoice_ref": invoice.e_invoice_ref,
    }
