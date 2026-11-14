"""The post-launch survey: branch → department → job title → save, and a self-chosen title
never raises anyone's access."""

from datetime import timedelta

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.members import profile_fix
from apps.members.callbacks import ProfileFix
from apps.members.models import AccessRole, Department, Membership, Position
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def _setup(company, member):
    company.profile_fix_until = timezone.now() + timedelta(days=14)  # as send_profile_fix opens it
    company.save(update_fields=["profile_fix_until"])
    branches = profile_fix.ensure_branches(company)
    department = Department.objects.create(company=company, name="Tijorat bo‘limi")
    worker = member.registered(company, user__telegram_id=7701)
    return branches, department, worker


async def test_the_whole_survey_saves_branch_department_and_title(dp, bot, company, member):
    branches, department, worker = await sync_to_async(_setup)(company, member)
    title = await sync_to_async(
        lambda: Position.objects.create(
            company=company,
            name="Farmatsevt X",
            role=AccessRole.objects.get(company=company, name="Employee"),
        )
    )()
    tg = updates.tg_user(7701)
    galaba = branches[1]

    for data in (
        ProfileFix(step="b", b=galaba.pk),
        ProfileFix(step="d", b=galaba.pk, d=department.pk),
        ProfileFix(step="p", b=galaba.pk, d=department.pk, p=title.pk),
        ProfileFix(step="ok", b=galaba.pk, d=department.pk, p=title.pk),
    ):
        await dp.feed_update(bot, updates.callback(tg, data.pack()))

    texts = [r.text for r in bot.requests if isinstance(r, EditMessageText)]
    assert texts[0] == profile_fix.ASK_DEPARTMENT and texts[1] == profile_fix.ASK_TITLE
    assert texts[-1].startswith(profile_fix.SAVED) and "G‘alaba" in texts[-1]
    saved = await sync_to_async(
        lambda: Membership.objects.select_related("position").get(pk=worker.pk)
    )()
    assert (saved.position_id, saved.department_id, saved.home_branch_id) == (
        title.pk,
        department.pk,
        galaba.pk,
    )
    assert await sync_to_async(lambda: list(saved.branches.values_list("pk", flat=True)))() == [
        galaba.pk
    ]


def test_a_manager_title_never_makes_anyone_a_manager(company, member):
    branches, _department, worker = _setup(company, member)
    manager = AccessRole.objects.get(company=company, name="Manager")
    boss = Position.objects.create(company=company, name="Bosh menejer", role=manager)
    before = worker.role_id

    assert profile_fix.apply(worker, b=branches[0].pk, d=0, p=boss.pk)

    worker.refresh_from_db()
    assert worker.position_id == boss.pk and worker.role_id == before


def test_an_owner_keeps_the_owner_role(company, member):
    branches, _department, _worker = _setup(company, member)
    owner = member.registered(company, "Owner")
    title = Position.objects.create(
        company=company,
        name="Kassir X",
        role=AccessRole.objects.get(company=company, name="Employee"),
    )
    assert profile_fix.apply(owner, b=branches[0].pk, d=0, p=title.pk)
    owner.refresh_from_db()
    assert owner.role.is_owner


def test_ids_from_elsewhere_are_refused(company, other_company, member):
    branches, _department, worker = _setup(company, member)
    foreign = Position.objects.create(company=other_company, name="Begona")
    assert not profile_fix.apply(worker, b=branches[0].pk, d=0, p=foreign.pk)
    assert not profile_fix.apply(worker, b=999999, d=0, p=foreign.pk)


async def test_the_survey_is_over_once_its_days_have_passed(dp, bot, company, member):
    """It used to take answers for ever: anyone still holding its message could move their own
    branch and job title months later. `send_profile_fix` opens it for some days."""
    branches, _department, worker = await sync_to_async(_setup)(company, member)
    await sync_to_async(
        lambda: (
            type(company)
            .objects.filter(pk=company.pk)
            .update(profile_fix_until=timezone.now() - timedelta(minutes=1))
        )
    )()
    data = ProfileFix(step="b", b=branches[1].pk)

    await dp.feed_update(bot, updates.callback(updates.tg_user(7701), data.pack()))

    answer = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    assert answer.text == profile_fix.GONE and answer.show_alert
    assert not [r for r in bot.requests if isinstance(r, EditMessageText)]
    saved = await sync_to_async(lambda: Membership.objects.get(pk=worker.pk))()
    assert saved.home_branch_id == worker.home_branch_id


def test_someone_still_waiting_says_where_they_work_but_gets_no_role_from_it(company, member):
    """What a person may do is decided by whoever approves them, never by a title they picked;
    and each answer leaves a row in the audit log."""
    from apps.audit.models import AuditLog

    branches, department, _worker = _setup(company, member)
    cashier = AccessRole.objects.get(company=company, name="Cashier")
    title = Position.objects.create(company=company, name="Kassir X", role=cashier)
    waiting = member.registered(company, user__telegram_id=7702)
    Membership.objects.filter(pk=waiting.pk).update(status=Membership.Status.PENDING)
    waiting.refresh_from_db()
    role_before = waiting.role_id

    assert profile_fix.apply(waiting, b=branches[0].pk, d=department.pk, p=title.pk)

    waiting.refresh_from_db()
    assert waiting.position_id == title.pk and waiting.role_id == role_before
    row = AuditLog.objects.filter(action="members.changed", company_id=company.pk).latest("pk")
    assert row.details["via"] == "profile_fix" and "position" in row.details["changes"]
