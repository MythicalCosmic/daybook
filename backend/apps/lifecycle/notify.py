"""Who hears about the people lifecycle, through the inbox (`apps.inbox.services.notify`).

- `lifecycle.record`: the person, when a record is given to them (the employee bot, with a way
  into the mini app's "My record").
- `lifecycle.explanation`: whoever gave the record, when the person explains.
"""

from apps.inbox import services as inbox
from apps.lifecycle import bot_messages
from apps.lifecycle.models import DisciplinaryRecord
from apps.members.models import Membership

RECORD = "lifecycle.record"
EXPLANATION = "lifecycle.explanation"


def record_screen(record: DisciplinaryRecord) -> str:
    return f"lifecycle.record:{record.pk}"


def record_issued(record_id: int) -> None:
    record = _load(record_id)
    if record is None or record.status == DisciplinaryRecord.Status.WITHDRAWN:
        return
    if record.membership.status != Membership.Status.APPROVED:
        return  # suspended: the bot leaves them alone; the record waits in the app
    inbox.notify(
        [record.membership],
        RECORD,
        title=lambda person: bot_messages.record_title(record),
        body=lambda person: bot_messages.record_body(record),
        app_screen=record_screen(record),
        target=record,
        severity="warning",
        dedupe_key=f"lifecycle.record:{record.pk}",
    )


def explanation(record_id: int) -> None:
    record = _load(record_id)
    if record is None or record.issued_by is None:
        return
    inbox.notify(
        [record.issued_by],
        EXPLANATION,
        title=lambda person: bot_messages.explanation_title(record),
        body=lambda person: bot_messages.explanation_body(record),
        url=f"/c/{record.company_id}/lifecycle/discipline?record={record.pk}",
        target=record,
        actor=record.membership,
    )


def _load(record_id: int) -> DisciplinaryRecord | None:
    return (
        DisciplinaryRecord.objects.select_related(
            "membership__user", "membership__company", "issued_by__user"
        )
        .filter(pk=record_id)
        .first()
    )
