"""Inbox buttons of task notifications (`apps.inbox.registry.register_action`): approving or
declining more time, from either bot or the dashboard's inbox. Each calls the service, which
checks who may decide and closes every other copy of the notification."""

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.members.models import Membership
from apps.tasks import services
from apps.tasks.models import Task


def approve_extension(item: Notification, by: Membership, reason: str) -> str:
    services.decide_extension(_task(item), by=by, approve=True)
    return _("More time given")


def decline_extension(item: Notification, by: Membership, reason: str) -> str:
    services.decide_extension(_task(item), by=by, approve=False)
    return _("The deadline stays")


def _task(item: Notification) -> Task:
    task = Task.objects.filter(pk=item.target_id, company_id=item.company_id).first()
    if task is None:
        raise DomainError(_("This task no longer exists."))
    return task
