"""Callback data shared by the backend, which sends the buttons, and the bot, which handles them."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class JoinAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class JoinDecision(CallbackData, prefix="join"):
    action: JoinAction
    membership_id: int


class JoinStep(StrEnum):
    """Steps of approving a join request in the bot when the company has several branches."""

    BRANCH = "b"  # toggle branch `pick`
    HOME = "h"  # `pick` is the home branch: approve
    ROLES = "r"  # show the roles
    ROLE = "s"  # `pick` is the role (0: the default one)
    APPROVE = "ok"
    BACK = "x"  # back to the request as it was


class JoinSetup(CallbackData, prefix="joins"):
    """The approver's choices travel in the button itself (no conversation state): `branches`
    is a dot-separated list of branch ids, `role` 0 for the default role, `nid` the inbox
    notification the message belongs to (0 for a classic request message)."""

    step: JoinStep
    membership_id: int
    nid: int = 0
    branches: str = ""
    role: int = 0
    pick: int = 0
