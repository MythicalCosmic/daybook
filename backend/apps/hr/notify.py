"""Who hears about HR records, through the inbox (`apps.inbox.services.notify`).

To HR (`hr.manage` holders who reach the person's branches; owners and top managers read it in
the owner bot): a document that expires, a contract that ends, a probation that finishes (with
[Keep] and [Extend 1 month]). Once per item and warning step: `dedupe_key` holds both.

To the person (the employee bot, with a way into the app): their contract is in force, a
document of theirs expires, their birthday or work anniversary.
"""

from datetime import date

from apps.hr import bot_messages
from apps.hr.models import Celebration, Contract, EmployeeDocument
from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

CONTRACT_READY = "hr.contract"
CONTRACT_SCREEN = "hr.contract"
DOCUMENT_EXPIRING = "hr.document_expiring"
CONTRACT_ENDING = "hr.contract_ending"
PROBATION_ENDING = "hr.probation_ending"
MY_DOCUMENT = "hr.my_document"
DOCUMENTS_SCREEN = "hr.documents"
CELEBRATION = "hr.celebration"


def recipients(person: Membership, perm: Perm = Perm.HR_MANAGE) -> list[Membership]:
    """Approved holders of `perm` who see one of the person's branches (everyone with every
    branch), the person themselves left out."""
    branch_ids = set(person.branches.values_list("pk", flat=True))
    found = []
    candidates = (
        members_with_perm(person.company, perm)
        .exclude(pk=person.pk)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    )
    for candidate in candidates:
        seen = scope.branch_ids(candidate)
        if seen is None or branch_ids & set(seen):
            found.append(candidate)
    return found


def contract_ready(contract_id: int) -> None:
    contract = (
        Contract.objects.select_related("membership__user", "membership__company")
        .filter(pk=contract_id, status=Contract.Status.ACTIVE)
        .first()
    )
    if contract is None or contract.membership.status != Membership.Status.APPROVED:
        return
    inbox.notify(
        [contract.membership],
        CONTRACT_READY,
        title=lambda person: bot_messages.contract_ready_title(),
        body=lambda person: bot_messages.contract_ready_body(contract),
        app_screen=CONTRACT_SCREEN,
        target=contract,
        dedupe_key=f"hr.contract:{contract.pk}",
    )


def document_expiring(document: EmployeeDocument, step: int, today: date) -> int:
    """HR hears; the person too, about a document they can see."""
    person = document.membership
    sent = inbox.notify(
        recipients(person),
        DOCUMENT_EXPIRING,
        title=lambda reader: bot_messages.document_title(document, today),
        body=lambda reader: bot_messages.document_body(document),
        url=f"/c/{document.company_id}/hr/documents?document={document.pk}",
        target=document,
        severity="warning" if step == 0 else None,
        dedupe_key=f"hr.document:{document.pk}:{step}",
    )
    if document.visible_to_employee and person.status == Membership.Status.APPROVED:
        sent += inbox.notify(
            [person],
            MY_DOCUMENT,
            title=lambda reader: bot_messages.my_document_title(document, today),
            body=lambda reader: bot_messages.my_document_body(document),
            app_screen=DOCUMENTS_SCREEN,
            target=document,
            dedupe_key=f"hr.my_document:{document.pk}:{step}",
        )
    return len(sent)


def contract_ending(contract: Contract, step: int, today: date) -> int:
    return len(
        inbox.notify(
            recipients(contract.membership),
            CONTRACT_ENDING,
            title=lambda reader: bot_messages.contract_title(contract, today),
            body=lambda reader: bot_messages.contract_body(contract),
            url=f"/c/{contract.company_id}/hr/contracts?contract={contract.pk}",
            target=contract,
            severity="warning" if step == 0 else None,
            dedupe_key=f"hr.contract_end:{contract.pk}:{step}",
        )
    )


def probation_ending(contract: Contract, step: int, today: date) -> int:
    return len(
        inbox.notify(
            recipients(contract.membership),
            PROBATION_ENDING,
            title=lambda reader: bot_messages.probation_title(contract, today),
            body=lambda reader: bot_messages.probation_body(contract),
            url=f"/c/{contract.company_id}/hr/contracts?contract={contract.pk}",
            target=contract,
            actions=[
                NotificationAction("keep", lambda reader: bot_messages.keep_label(), "primary"),
                NotificationAction("extend", lambda reader: bot_messages.extend_label()),
            ],
            dedupe_key=f"hr.probation:{contract.pk}:{contract.probation_until}:{step}",
        )
    )


def greet(celebration: Celebration) -> int:
    """The person's own greeting on their day."""
    person = celebration.membership
    if person.status != Membership.Status.APPROVED:
        return 0
    if celebration.kind == Celebration.Kind.BIRTHDAY:

        def title(reader):
            return bot_messages.birthday_greeting_title()

    else:

        def title(reader):
            return bot_messages.anniversary_greeting_title(celebration.years or 1)

    return len(
        inbox.notify(
            [person],
            CELEBRATION,
            title=title,
            body=lambda reader: bot_messages.greeting_body(person.company.name),
            target=celebration,
            dedupe_key=f"hr.celebration:{celebration.pk}",
        )
    )
