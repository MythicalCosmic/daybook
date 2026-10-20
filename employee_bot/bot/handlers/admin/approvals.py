"""Join requests decided in the bot.

Approvers get a request as an inbox notification (kind `members.join`) with Approve / Reject.
Reject goes through the inbox's generic button handler. Approve is answered here, before that
handler (this router runs first): in a company with one branch it approves at once; with
several it turns the message into a small card to pick the branches (and the role), then the
home branch when there are several, and approves. The choices travel in the buttons
(`JoinSetup`), so nothing breaks if two approvers open the card at once: the first approval
wins and every copy shows it.

Older request messages (`JoinDecision` buttons, also what platform admins get) take the same
path.
"""

from contextlib import suppress
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.inbox import bot_messages as inbox_messages
from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.members import bot_messages, scope, services
from apps.members.callbacks import JoinAction, JoinDecision, JoinSetup, JoinStep
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

router = Router(name="approvals")

JOIN_KIND = "members.join"


@dataclass
class Answer:
    alert: str | None = None
    message: bot_messages.BotMessage | None = None


class JoinApproveButton(Filter):
    """The Approve button of a `members.join` inbox notification."""

    async def __call__(self, callback: CallbackQuery, callback_data: InboxAction) -> bool:
        return await _is_join_notification(callback_data.notification_id)


@sync_to_async
def _is_join_notification(notification_id: int) -> bool:
    return Notification.objects.filter(pk=notification_id, kind=JOIN_KIND).exists()


@router.callback_query(InboxAction.filter(F.key == "approve"), JoinApproveButton())
async def approve_from_inbox(callback: CallbackQuery, callback_data: InboxAction, user: User):
    answer = await _start(user, notification_id=callback_data.notification_id)
    await _reply(callback, answer)


@router.callback_query(JoinDecision.filter())
async def decide_join_request(
    callback: CallbackQuery, callback_data: JoinDecision, user: User
) -> None:
    if callback_data.action == JoinAction.APPROVE:
        answer = await _start(user, membership_id=callback_data.membership_id)
    else:
        answer = await _reject(user, callback_data.membership_id)
    await _reply(callback, answer)


@router.callback_query(JoinSetup.filter())
async def join_setup_step(callback: CallbackQuery, callback_data: JoinSetup, user: User) -> None:
    await _reply(callback, await _step(user, callback_data))


async def _reply(callback: CallbackQuery, answer: Answer) -> None:
    if answer.message is not None and isinstance(callback.message, Message):
        text, markup = answer.message
        # Unchanged or too old to edit: the alert still tells the approver what happened.
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(answer.alert, show_alert=answer.alert is not None)


# The steps (database work in a worker thread) ---------------------------------------------


@sync_to_async
def _start(user: User, *, membership_id: int | None = None, notification_id: int = 0) -> Answer:
    if notification_id:
        item = (
            Notification.objects.select_related("recipient")
            .filter(pk=notification_id, recipient__user=user)
            .first()
        )
        if item is None:
            return Answer(_("You don't have access to this."))
        membership_id = item.target_id
    membership = services.get_join_request(membership_id or 0)
    if membership is None:
        return Answer(_("This request no longer exists."))
    problem = _problem(user, membership)
    if problem is not None:
        return problem
    branches = _branches(membership, user)
    if len(branches) == 1:
        only = branches[0]
        return _approve(
            user, membership, notification_id=notification_id, branches=[only], home=only.pk
        )
    if not branches:
        return _approve(user, membership, notification_id=notification_id)
    approver = _approver(user, membership)
    home = approver.home_branch_id if approver is not None else None
    chosen = [home] if home in {branch.pk for branch in branches} else []
    return Answer(
        message=bot_messages.join_setup(
            membership,
            branches=branches,
            chosen=chosen,
            role=_role(membership, 0),
            nid=notification_id,
        )
    )


@sync_to_async
def _step(user: User, data: JoinSetup) -> Answer:
    membership = services.get_join_request(data.membership_id)
    if membership is None:
        return Answer(_("This request no longer exists."))
    if data.step == JoinStep.BACK:
        return Answer(message=_original(membership, data.nid, user))
    problem = _problem(user, membership)
    if problem is not None:
        return problem
    branches = _branches(membership, user)
    ids = {branch.pk for branch in branches}
    chosen = [pk for pk in bot_messages.unpack_branches(data.branches) if pk in ids]
    role_id = data.role

    if data.step == JoinStep.BRANCH and data.pick in ids:
        chosen = (
            [pk for pk in chosen if pk != data.pick]
            if data.pick in chosen
            else [
                *chosen,
                data.pick,
            ]
        )
    elif data.step == JoinStep.ROLES:
        approver = _approver(user, membership)
        roles = [
            role
            for role in AccessRole.objects.for_company(membership.company).order_by(
                "-is_default", "is_owner", "name"
            )
            if user.is_platform_admin or services.may_assign_role(approver, role)
        ]
        return Answer(
            message=bot_messages.join_roles(
                membership, roles=roles, current_id=role_id, chosen=chosen, nid=data.nid
            )
        )
    elif data.step == JoinStep.ROLE:
        role_id = data.pick
    elif data.step == JoinStep.APPROVE:
        if not chosen:
            return Answer(_("Choose at least one branch."))
        if len(chosen) > 1:
            return Answer(
                message=bot_messages.join_home(
                    membership, branches=branches, chosen=chosen, role_id=role_id, nid=data.nid
                )
            )
        return _approve(
            user,
            membership,
            notification_id=data.nid,
            branches=[b for b in branches if b.pk in chosen],
            home=chosen[0],
            role_id=role_id,
        )
    elif data.step == JoinStep.HOME and data.pick in chosen:
        return _approve(
            user,
            membership,
            notification_id=data.nid,
            branches=[b for b in branches if b.pk in chosen],
            home=data.pick,
            role_id=role_id,
        )
    return Answer(
        message=bot_messages.join_setup(
            membership,
            branches=branches,
            chosen=chosen,
            role=_role(membership, role_id),
            nid=data.nid,
        )
    )


@sync_to_async
def _reject(user: User, membership_id: int) -> Answer:
    try:
        membership = services.decide(membership_id, JoinAction.REJECT, by=user)
    except PermissionDenied as exc:
        return Answer(str(exc))
    except DomainError as exc:
        current = services.get_join_request(membership_id)
        return Answer(str(exc), bot_messages.join_request(current) if current else None)
    return Answer(message=bot_messages.join_request(membership))


def _approve(
    user: User,
    membership: Membership,
    *,
    notification_id: int,
    branches: list[Branch] | None = None,
    home: int | None = None,
    role_id: int = 0,
) -> Answer:
    role = _role(membership, role_id) if role_id else None
    home_branch = next((b for b in branches or [] if b.pk == home), None)
    try:
        membership = services.approve(
            membership, by=user, role=role, branches=branches, home_branch=home_branch
        )
    except PermissionDenied as exc:
        return Answer(str(exc))
    except DomainError as exc:
        current = services.get_join_request(membership.pk)
        return Answer(str(exc), _original(current, notification_id, user) if current else None)
    return Answer(message=_original(membership, notification_id, user))


def _problem(user: User, membership: Membership) -> Answer | None:
    """Why this person can't approve this request now, as an answer; None when they can."""
    if not services.can(user, membership.company, Perm.MEMBERS_APPROVE):
        return Answer(_("You don't have permission to do this."))
    if membership.status != Membership.Status.PENDING:
        status = membership.get_status_display().lower()
        return Answer(_("This request is already %(status)s.") % {"status": status})
    return None


def _original(membership: Membership, notification_id: int, user: User):
    """The request message as it is now: the inbox copy, or the classic message."""
    if notification_id:
        item = Notification.objects.filter(pk=notification_id, recipient__user=user).first()
        if item is not None:
            outcome = ""
            if membership.status != Membership.Status.PENDING:
                label = (
                    _("Approved")
                    if membership.status == Membership.Status.APPROVED
                    else (_("Rejected"))
                )
                decider = membership.decided_by.get_full_name() if membership.decided_by else ""
                outcome = inbox_messages.outcome_line(label, decider)
            return inbox_messages.notification(item, audience="employee", outcome=outcome)
    return bot_messages.join_request(membership)


def _branches(membership: Membership, user: User) -> list[Branch]:
    """The company's active branches the approver may hand out (all of them for someone who
    sees every branch)."""
    branches = Branch.objects.filter(company_id=membership.company_id, is_active=True)
    approver = _approver(user, membership)
    allowed = scope.branch_ids(approver) if approver is not None else None
    if allowed is not None:
        branches = branches.filter(pk__in=allowed)
    return list(branches.order_by("order", "pk"))


def _approver(user: User, membership: Membership) -> Membership | None:
    approver = services.get_membership(user, membership.company)
    if approver is None or approver.status != Membership.Status.APPROVED:
        return None
    return approver


def _role(membership: Membership, role_id: int) -> AccessRole | None:
    roles = AccessRole.objects.for_company(membership.company)
    if role_id:
        found = roles.filter(pk=role_id).first()
        if found is not None:
            return found
    return roles.filter(is_default=True).first()
