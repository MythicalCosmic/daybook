"""Business logic of the owner console: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.
"""

import json

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console.audit_actions import ConsoleAction
from apps.console.models import SavedView
from apps.core.exceptions import DomainError
from apps.members.models import Membership

# A view stores filters and columns, not data; this is generous.
MAX_STATE_BYTES = 32 * 1024
EDITABLE = ("module", "name", "state", "is_shared", "order")


@transaction.atomic
def create_saved_view(
    *,
    by: Membership,
    module: str,
    name: str,
    state: dict,
    is_shared: bool = False,
    order: int = 0,
) -> SavedView:
    _check_state(state)
    view = SavedView(
        company_id=by.company_id,
        membership=by,
        module=module,
        name=name,
        state=state,
        is_shared=is_shared,
        order=order,
    )
    _save(view)
    if view.is_shared:
        _audit(ConsoleAction.SAVED_VIEW_SHARED, view, by)
    return view


@transaction.atomic
def update_saved_view(view: SavedView, *, by: Membership, **changes) -> SavedView:
    """Change your own view; `changes` may hold module, name, state, is_shared and order."""
    _ensure_own(view, by)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} on a saved view.")
    if "state" in changes:
        _check_state(changes["state"])
    was_shared = view.is_shared
    for name, value in changes.items():
        setattr(view, name, value)
    _save(view)
    if view.is_shared and not was_shared:
        _audit(ConsoleAction.SAVED_VIEW_SHARED, view, by)
    elif was_shared and not view.is_shared:
        _audit(ConsoleAction.SAVED_VIEW_UNSHARED, view, by)
    elif view.is_shared:
        _audit(ConsoleAction.SAVED_VIEW_CHANGED, view, by, changed=sorted(changes))
    return view


@transaction.atomic
def delete_saved_view(view: SavedView, *, by: Membership) -> None:
    _ensure_own(view, by)
    if view.is_shared:
        _audit(ConsoleAction.SAVED_VIEW_DELETED, view, by)
    view.delete()


def _ensure_own(view: SavedView, by: Membership) -> None:
    if view.membership_id != by.pk:
        raise PermissionDenied(_("Only the person who saved this view can change it."))


def _check_state(state) -> None:
    if not isinstance(state, dict):
        raise DomainError(_("A saved view's state must be an object."))
    if len(json.dumps(state)) > MAX_STATE_BYTES:
        raise DomainError(_("This view holds too much to save."))


def _save(view: SavedView) -> None:
    try:
        with transaction.atomic():
            view.save()
    except IntegrityError:
        raise DomainError(_("You already have a view with this name here.")) from None


def _audit(action: ConsoleAction, view: SavedView, by: Membership, **details) -> None:
    audit.record(
        action,
        company_id=view.company_id,
        actor=by.user,
        target=view,
        module=view.module,
        **details,
    )
