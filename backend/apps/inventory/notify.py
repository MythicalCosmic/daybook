"""Who hears about stock, through the inbox (`apps.inbox.services.notify`).

Owners and heads of pharmacy (stock.manage who see the branch) get the expiry digest, recalls,
disputed transfers, destruction dates and receipts waiting for posting, with an [Open] button
into the dashboard. A pharmacy's staff (stock.operate) hear of a transfer coming to them, with
[Received ✓] (receives every line as sent; differences need the screen) and [Open] into the
app. Owners hear of a count shortage above the tolerance; stock.controlled holders of the
controlled register's month and its differences. Each notice goes out once: `dedupe_key`
names the record and the step.
"""

from __future__ import annotations

from datetime import date

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.core.money import format_money
from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

EXPIRY_DIGEST = "inventory.expiry_digest"
TRANSFER_INCOMING = "inventory.transfer_incoming"
TRANSFER_DISPUTED = "inventory.transfer_disputed"
RECALL = "inventory.recall"
COUNT_SHORTAGE = "inventory.count_shortage"
COST_JUMP = "inventory.cost_jump"
DESTROY_DUE = "inventory.destroy_due"
CONTROLLED_CLOSE_DUE = "inventory.controlled_close_due"
CONTROLLED_MISMATCH = "inventory.controlled_mismatch"
RECEIPT_WAITING = "inventory.receipt_waiting"
WRITEOFF_WAITING = "inventory.writeoff_waiting"

RECEIVED = "received"
RECEIVED_LABEL = gettext_lazy("Received ✓")


def _day(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _url(company_id: int, path: str) -> str:
    return f"/c/{company_id}/stock/{path}"


def holders(company, perm, branch_ids=None, *, owners: bool = True) -> list[Membership]:
    """Approved holders of `perm` who see any of `branch_ids` (every holder when None)."""
    found = []
    for person in members_with_perm(company, perm).select_related("user", "role", "company"):
        if not owners and person.role.is_owner:
            continue
        seen = scope.branch_ids(person)
        if branch_ids is None or seen is None or set(seen) & set(branch_ids):
            found.append(person)
    return found


def managers(company, branch_ids) -> list[Membership]:
    return holders(company, Perm.STOCK_MANAGE, branch_ids)


def staff(company, branch_id) -> list[Membership]:
    """The people working at the branch who handle stock (not the owners)."""
    found = {}
    for perm in (Perm.STOCK_OPERATE, Perm.STOCK_MANAGE):
        for person in members_with_perm(company, perm).select_related("user", "role", "company"):
            if person.role.is_owner:
                continue
            if person.branches.filter(pk=branch_id).exists():
                found[person.pk] = person
    return list(found.values())


def _money(company, amount, person) -> str:
    return format_money(amount, company.base_currency, person.user.language)


# Receipts ----------------------------------------------------------------------------------


def receipt_waiting(receipt_id: int, *, reminder: bool = False) -> int:
    from apps.inventory.models import GoodsReceipt

    receipt = (
        GoodsReceipt.objects.select_related("company", "branch", "supplier")
        .filter(
            pk=receipt_id,
            status__in=(GoodsReceipt.Status.SUBMITTED, GoodsReceipt.Status.DRAFT),
        )
        .first()
    )
    if receipt is None or (receipt.status == GoodsReceipt.Status.DRAFT and not reminder):
        return 0
    people = managers(receipt.company, [receipt.branch_id])
    invoice = receipt.supplier_invoice_number or f"#{receipt.pk}"
    draft = receipt.status == GoodsReceipt.Status.DRAFT

    def title(person):
        if draft:
            return _("Receipt %(invoice)s from %(supplier)s is still a draft") % {
                "invoice": invoice,
                "supplier": receipt.supplier.name,
            }
        return _("Receipt %(invoice)s from %(supplier)s waits for posting") % {
            "invoice": invoice,
            "supplier": receipt.supplier.name,
        }

    sent = inbox.notify(
        people,
        RECEIPT_WAITING,
        title=title,
        body=lambda person: (
            _("%(branch)s, invoice of %(day)s.")
            % {"branch": receipt.branch.name, "day": _day(receipt.supplier_invoice_date)}
        ),
        url=_url(receipt.company_id, f"receipts/{receipt.pk}"),
        target=receipt,
        dedupe_key=f"inventory.receipt_waiting:{receipt.pk}:{'r' if reminder else 's'}",
    )
    return len(sent)


def cost_jump(receipt_id: int, jumps: list[dict]) -> int:
    from apps.inventory.models import GoodsReceipt

    receipt = (
        GoodsReceipt.objects.select_related("company", "branch", "supplier")
        .filter(pk=receipt_id)
        .first()
    )
    if receipt is None or not jumps:
        return 0
    people = holders(receipt.company, Perm.FINANCE_VIEW, [receipt.branch_id])
    names = ", ".join(row["product"] for row in jumps[:5])
    sent = inbox.notify(
        people,
        COST_JUMP,
        title=lambda person: (
            ngettext(
                "%(supplier)s raised the price of %(count)d item",
                "%(supplier)s raised the price of %(count)d items",
                len(jumps),
            )
            % {"supplier": receipt.supplier.name, "count": len(jumps)}
        ),
        body=lambda person: (
            _("Receipt %(number)s: %(names)s.") % {"number": receipt.number, "names": names}
        ),
        url=_url(receipt.company_id, f"receipts/{receipt.pk}"),
        target=receipt,
        dedupe_key=f"inventory.cost_jump:{receipt.pk}",
    )
    return len(sent)


# Transfers ---------------------------------------------------------------------------------


def transfer_incoming(transfer_id: int) -> int:
    from apps.inventory.models import StockTransfer

    transfer = (
        StockTransfer.objects.select_related("company", "from_branch", "to_branch")
        .filter(pk=transfer_id, status=StockTransfer.Status.SENT)
        .first()
    )
    if transfer is None:
        return 0
    items = transfer.lines.count()
    people = staff(transfer.company, transfer.to_branch_id)
    sent = inbox.notify(
        people,
        TRANSFER_INCOMING,
        title=lambda person: (
            ngettext(
                "Transfer from %(branch)s: %(count)d item",
                "Transfer from %(branch)s: %(count)d items",
                items,
            )
            % {"branch": transfer.from_branch.name, "count": items}
        ),
        body=lambda person: (
            _(
                "%(number)s. Check it when it arrives: Received ✓ takes every line as sent; a "
                "difference is entered in the app."
            )
            % {"number": transfer.number}
        ),
        app_screen=f"stock.transfer:{transfer.pk}",
        url=_url(transfer.company_id, f"transfers/{transfer.pk}"),
        target=transfer,
        actions=[NotificationAction(key=RECEIVED, label=RECEIVED_LABEL, style="primary")],
        dedupe_key=f"inventory.transfer_incoming:{transfer.pk}",
    )
    return len(sent)


def received_action(notification, by: Membership, reason: str) -> str:
    """[Received ✓]: every line as sent."""
    from apps.core.exceptions import DomainError
    from apps.inventory import services
    from apps.inventory.models import StockTransfer

    transfer = (
        StockTransfer.objects.filter(company_id=notification.company_id, pk=notification.target_id)
        .select_related("to_branch")
        .first()
    )
    if transfer is None:
        raise DomainError(_("This transfer is gone."))
    if not (by.has_perm(Perm.STOCK_OPERATE) or by.has_perm(Perm.STOCK_MANAGE)):
        raise DomainError(_("You don't have permission to do this."))
    seen = scope.branch_ids(by)
    if seen is not None and transfer.to_branch_id not in seen:
        raise DomainError(_("This transfer goes to another pharmacy."))
    services.receive_transfer(transfer, by=by)
    return _("Received")


def transfer_disputed(transfer_id: int) -> int:
    from apps.inventory.models import StockTransfer

    transfer = (
        StockTransfer.objects.select_related("company", "from_branch", "to_branch")
        .filter(pk=transfer_id, status=StockTransfer.Status.DISPUTED)
        .first()
    )
    if transfer is None:
        return 0
    people = managers(transfer.company, [transfer.from_branch_id, transfer.to_branch_id])
    sent = inbox.notify(
        people,
        TRANSFER_DISPUTED,
        title=lambda person: (
            _("Transfer %(number)s arrived short at %(branch)s")
            % {"number": transfer.number, "branch": transfer.to_branch.name}
        ),
        body=lambda person: (
            _(
                "The missing goods stay on the way until a manager decides: lost, found or back at "
                "%(branch)s."
            )
            % {"branch": transfer.from_branch.name}
        ),
        url=_url(transfer.company_id, f"transfers/{transfer.pk}"),
        target=transfer,
        severity="warning",
        dedupe_key=f"inventory.transfer_disputed:{transfer.pk}",
    )
    return len(sent)


# Write-offs ---------------------------------------------------------------------------------


def writeoff_waiting(writeoff_id: int) -> int:
    from apps.inventory.models import WriteOff

    writeoff = (
        WriteOff.objects.select_related("company", "branch")
        .filter(pk=writeoff_id, status=WriteOff.Status.PROPOSED)
        .first()
    )
    if writeoff is None:
        return 0
    people = [
        person
        for person in managers(writeoff.company, [writeoff.branch_id])
        if person.pk != writeoff.proposed_by_id
    ]
    lines = writeoff.lines.count()
    sent = inbox.notify(
        people,
        WRITEOFF_WAITING,
        title=lambda person: (
            ngettext(
                "Write-off at %(branch)s waits for approval: %(count)d series",
                "Write-off at %(branch)s waits for approval: %(count)d series",
                lines,
            )
            % {"branch": writeoff.branch.name, "count": lines}
        ),
        body=lambda person: str(writeoff.get_reason_display()),
        url=_url(writeoff.company_id, f"write-offs/{writeoff.pk}"),
        target=writeoff,
        dedupe_key=f"inventory.writeoff_waiting:{writeoff.pk}",
    )
    return len(sent)


def destroy_due(writeoff, step: str, today: date) -> int:
    """`step`: "soon" (10 days left) or "due" (the last day)."""
    people = managers(writeoff.company, [writeoff.branch_id])
    if writeoff.approved_by_id and all(p.pk != writeoff.approved_by_id for p in people):
        approver = Membership.objects.filter(
            pk=writeoff.approved_by_id, status=Membership.Status.APPROVED
        ).first()
        if approver is not None:
            people.append(approver)
    day = _day(writeoff.destroy_by)

    def title(person):
        if step == "due":
            return _("Destroy the goods of %(number)s today") % {"number": writeoff.number}
        return _("Destroy the goods of %(number)s by %(day)s") % {
            "number": writeoff.number,
            "day": day,
        }

    sent = inbox.notify(
        people,
        DESTROY_DUE,
        title=title,
        body=lambda person: (
            _(
                "Unfit goods are destroyed within the legal term, by a commission, with photos and "
                "an act: %(branch)s."
            )
            % {"branch": writeoff.branch.name}
        ),
        url=_url(writeoff.company_id, f"write-offs/{writeoff.pk}"),
        target=writeoff,
        severity="warning" if step == "due" else None,
        dedupe_key=f"inventory.destroy_due:{writeoff.pk}:{step}",
    )
    return len(sent)


# Counts --------------------------------------------------------------------------------------


def count_shortage(count_id: int) -> int:
    from apps.inventory.models import StockCount

    count = StockCount.objects.select_related("company", "branch").filter(pk=count_id).first()
    if count is None or count.value_difference is None:
        return 0
    owners = [
        person
        for person in members_with_perm(count.company, Perm.FINANCE_VIEW).select_related(
            "user", "role", "company"
        )
        if person.role.is_owner
    ]
    sent = inbox.notify(
        owners,
        COUNT_SHORTAGE,
        title=lambda person: (
            _("Stock count at %(branch)s: %(amount)s short")
            % {
                "branch": count.branch.name,
                "amount": _money(count.company, -count.value_difference, person),
            }
        ),
        body=lambda person: _("At cost. The count's page shows each series."),
        url=_url(count.company_id, f"counts/{count.pk}"),
        target=count,
        severity="warning",
        dedupe_key=f"inventory.count_shortage:{count.pk}",
    )
    return len(sent)


# Recalls --------------------------------------------------------------------------------------


def recall(recall_id: int) -> int:
    from apps.inventory.models import RecallNotice

    notice = RecallNotice.objects.select_related("company", "product").filter(pk=recall_id).first()
    if notice is None:
        return 0
    found = notice.found or []
    branch_ids = sorted({row["branch_id"] for row in found})
    people = managers(notice.company, branch_ids or None)
    name = notice.product.name if notice.product_id else notice.inn_or_name

    def body(person):
        seen = scope.branch_ids(person)
        rows = [row for row in found if seen is None or row["branch_id"] in seen]
        if not rows:
            return _("Not found in stock.")
        return "; ".join(
            _("%(quantity)s parts at %(branch)s")
            % {"quantity": row["quantity"], "branch": row["branch"]}
            for row in rows
        )

    sent = inbox.notify(
        people,
        RECALL,
        title=lambda person: (
            _("Recall: series %(series)s of %(product)s")
            % {"series": notice.series, "product": name}
        ),
        body=body,
        url=_url(notice.company_id, f"recalls/{notice.pk}"),
        target=notice,
        severity="warning",
        dedupe_key=f"inventory.recall:{notice.pk}",
    )
    return len(sent)


# The daily scan -----------------------------------------------------------------------------


def expiry_digest(company, branch, rows: list[dict], today: date) -> int:
    """One digest per branch and day: batches that reached an expiry step today (each step
    once per batch), plus the mandatory medicines missing there."""
    batches = [row for row in rows if row.get("kind") == "batch"]
    missing = [row for row in rows if row.get("kind") == "missing"]
    if not batches and not missing:
        return 0
    people = managers(company, [branch.pk])
    expired = [row for row in batches if row["step"] == 0]
    soon = [row for row in batches if row["step"] > 0]
    value = sum((row["value"] for row in batches), 0)

    def title(person):
        if soon or expired:
            return ngettext(
                "%(branch)s: %(count)d batch reaches its expiry warning, %(amount)s",
                "%(branch)s: %(count)d batches reach their expiry warning, %(amount)s",
                len(batches),
            ) % {
                "branch": branch.name,
                "count": len(batches),
                "amount": _money(company, value, person),
            }
        return ngettext(
            "%(branch)s: %(count)d mandatory medicine is missing",
            "%(branch)s: %(count)d mandatory medicines are missing",
            len(missing),
        ) % {"branch": branch.name, "count": len(missing)}

    def body(person):
        lines = []
        if expired:
            lines.append(
                _("Expired, off sale: %(names)s.")
                % {"names": ", ".join(f"{row['product']} ({row['series']})" for row in expired[:8])}
            )
        for row in soon[:12]:
            lines.append(
                _("%(product)s, series %(series)s: expires %(day)s")
                % {
                    "product": row["product"],
                    "series": row["series"],
                    "day": _day(row["expires_on"]),
                }
            )
        if missing:
            lines.append(
                _("Mandatory list, none on sale: %(names)s.")
                % {"names": ", ".join(row["product"] for row in missing[:8])}
            )
        return "\n".join(lines)

    sent = inbox.notify(
        people,
        EXPIRY_DIGEST,
        title=title,
        body=body,
        url=_url(company.pk, f"expiry?branch={branch.pk}"),
        app_screen="stock.expiry",  # a head of pharmacy opens the app's expiry check
        target=branch,
        severity="warning" if expired else None,
        dedupe_key=f"inventory.expiry_digest:{branch.pk}:{today.isoformat()}",
    )
    return len(sent)


def controlled_close_due(company, branch, month: date, step: str, today: date) -> int:
    """`step`: "remind" (the 1st) or "late" (after the close day, not closed)."""
    people = holders(company, Perm.STOCK_CONTROLLED, [branch.pk])
    label = month.strftime("%m.%Y")

    def title(person):
        if step == "late":
            return _("Close %(month)s in the controlled register at %(branch)s: it is late") % {
                "month": label,
                "branch": branch.name,
            }
        return _("Count the controlled medicines at %(branch)s and close %(month)s") % {
            "month": label,
            "branch": branch.name,
        }

    sent = inbox.notify(
        people,
        CONTROLLED_CLOSE_DUE,
        title=title,
        body=lambda person: (
            _("The monthly inventory of the controlled register is due by the %(day)s.")
            % {"day": company.stock_settings.controlled_close_day}
        ),
        url=_url(company.pk, f"journals?branch={branch.pk}&month={month.isoformat()}"),
        target=branch,
        severity="warning" if step == "late" else None,
        dedupe_key=f"inventory.controlled_close_due:{branch.pk}:{month.isoformat()}:{step}",
    )
    return len(sent)


def controlled_mismatch(period, today: date, days: int) -> int:
    """A difference in the controlled register: owners and stock.controlled holders, daily
    until it is reported."""
    company = period.company
    people = {
        person.pk: person for person in holders(company, Perm.STOCK_CONTROLLED, [period.branch_id])
    }
    for person in members_with_perm(company, Perm.COMPANY_SETTINGS).select_related(
        "user", "role", "company"
    ):
        if person.role.is_owner:
            people[person.pk] = person
    sent = inbox.notify(
        list(people.values()),
        CONTROLLED_MISMATCH,
        title=lambda person: (
            _("Controlled register difference: %(product)s at %(branch)s")
            % {"product": period.product.name, "branch": period.branch.name}
        ),
        body=lambda person: (
            _(
                "Counted %(counted)s, the register says %(closing)s. Report it to the internal "
                "affairs bodies and the Ministry of Health within %(days)s days, then mark it "
                "reported."
            )
            % {
                "counted": period.counted.normalize(),
                "closing": period.closing.normalize(),
                "days": days,
            }
        ),
        url=_url(
            company.pk, f"journals?branch={period.branch_id}&month={period.month.isoformat()}"
        ),
        target=period,
        severity="critical",
        dedupe_key=f"inventory.controlled_mismatch:{period.pk}:{today.isoformat()}",
    )
    return len(sent)
