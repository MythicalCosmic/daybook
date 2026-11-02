"""Who hears about HR records, through the inbox (`apps.inbox.services.notify`).

- `hr.contract`: the person, when a contract of theirs comes into force (read it in the app).
"""

from apps.hr import bot_messages
from apps.hr.models import Contract
from apps.inbox import services as inbox
from apps.members.models import Membership

CONTRACT_READY = "hr.contract"
CONTRACT_SCREEN = "hr.contract"


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
