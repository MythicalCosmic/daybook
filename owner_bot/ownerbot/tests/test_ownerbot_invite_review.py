"""Review of `/invite` (bulk/review): each test here failed on bulk/core (45cd120)."""

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.members.models import JoinLink
from ownerbot import invite
from ownerbot.callbacks import InviteNew

pytestmark = pytest.mark.django_db


def test_a_branch_with_a_long_name_still_gets_a_team_link(company, member):
    owner = member(company, "Owner", user__telegram_id=7601)
    # Branch names take up to 100 characters ("Dorixona №12, Chilonzor tumani, ..." happens).
    branch = BranchFactory(company=company, name="Dorixona " + "x" * 91)
    step = InviteNew(company=company.pk, branch=branch.pk, places=0, days=7)

    made = invite.new_link(owner, step)  # the last of the three taps

    assert isinstance(made, JoinLink), made
    assert len(made.name) <= 100
