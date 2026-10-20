"""The Wave 0 stand-ins other packages code against: final signatures, safe answers."""

import inspect
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.ai import availability, receipts, writer
from apps.hr.queries import employment_dates
from apps.lifecycle.contracts import unpaid_days
from apps.members import services as members
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory
from apps.payroll.contracts import cost_rate
from apps.timeoff.queries import balance, leave_summary

pytestmark = pytest.mark.django_db


def test_ai_is_not_configured_until_package_k(company, member):
    owner = member.registered(company, "Owner")

    status = availability.status(company, membership=owner)

    assert status.state == availability.AIState.NOT_CONFIGURED
    assert not status.available
    assert availability.status(company).state == "not_configured"
    assert availability.AIStatus(availability.AIState.AVAILABLE).available


def test_receipt_scans_and_the_writer_fall_back(company, member):
    worker = member.registered(company)

    assert receipts.start_scan(b"jpeg", by=worker, source="bot") is None
    assert writer.write_briefing({"sales": "1"}, kind="morning", language="uz") is None
    assert writer.explain_insight({"value": "1"}, language="ru") is None
    with pytest.raises(ValueError):
        receipts.start_scan(b"jpeg", by=worker, source="email")


def test_the_writers_result_shapes_validate():
    content = writer.BriefingContent.model_validate(
        {
            "headline": "Sales up 4%",
            "sections": [{"title": "Sales", "bullets": ["Chilonzor 12 500 000 so'm"]}],
            "actions": [{"label": "Open", "url": "/c/1/sales"}],
        }
    )
    text = writer.InsightText(title="Cash short", explanation="…", suggested_action="Check")

    assert content.sections[0].bullets == ["Chilonzor 12 500 000 so'm"]
    assert text.title == "Cash short"


@pytest.mark.parametrize(
    ("function", "signature"),
    [
        (availability.status, "(company, *, membership=None)"),
        (receipts.start_scan, "(file, *, by, source)"),
        (writer.write_briefing, "(facts, *, kind, language)"),
        (writer.explain_insight, "(facts, *, language)"),
        (unpaid_days, "(membership, start, end)"),
        (cost_rate, "(membership, day)"),
        (employment_dates, "(company, member_ids)"),
        (leave_summary, "(company, start, end, *, member_ids=None)"),
        (balance, "(membership, *, kind='annual', on)"),
    ],
)
def test_the_contract_signatures_are_the_final_ones(function, signature):
    """Parameter names, kinds and defaults as docs/PLAN-OWNER.md fixes them."""
    plain = inspect.signature(function).replace(return_annotation=inspect.Signature.empty)
    shown = plain.replace(
        parameters=[
            parameter.replace(annotation=inspect.Parameter.empty)
            for parameter in plain.parameters.values()
        ]
    )
    assert str(shown) == signature


def test_lifecycle_and_payroll_stand_ins(company, member):
    worker = member.registered(company)

    assert unpaid_days(worker, date(2026, 10, 1), date(2026, 10, 31)) == 0
    assert cost_rate(worker, date(2026, 10, 20)) is None


def local(moment: datetime, company) -> date:
    return timezone.localtime(moment, ZoneInfo(company.timezone)).date()


def test_employment_starts_at_the_latest_approval(company, member):
    manager = member.registered(company, "Manager")
    joiner = MembershipFactory(company=company)
    members.approve(joiner, by=manager.user)
    joiner.refresh_from_db()

    dates = employment_dates(company, [joiner.pk])

    assert dates == {joiner.pk: (local(joiner.decided_at, company), None)}


def test_employment_ends_on_the_last_day_given(company, member):
    owner = member.registered(company, "Owner")
    leaver = member.registered(company)
    today = timezone.localdate(timezone=ZoneInfo(company.timezone))
    members.offboard(leaver, by=owner.user, terminated_on=today - timedelta(days=3))

    [(start, end)] = employment_dates(company, [leaver.pk]).values()

    assert end == today - timedelta(days=3)
    assert start == local(leaver.onboarded_at, company)


def test_blocked_people_end_the_day_they_were_blocked(company, member):
    owner = member.registered(company, "Owner")
    blocked = member.registered(company)
    members.block(blocked, by=owner.user)
    blocked.refresh_from_db()

    [(_start, end)] = employment_dates(company, [blocked.pk]).values()

    assert end == local(blocked.decided_at, company)


def test_people_who_never_joined_or_belong_elsewhere_are_left_out(company, other_company, member):
    pending = MembershipFactory(company=company)
    rejected = MembershipFactory(company=company, status=Membership.Status.REJECTED)
    stranger = member.registered(other_company)
    current = member.registered(company)

    dates = employment_dates(company, [pending.pk, rejected.pk, stranger.pk, current.pk])

    assert set(dates) == {current.pk}
    assert dates[current.pk][1] is None


def test_a_decimal_rate_type_is_promised():
    assert cost_rate.__annotations__["return"] == Decimal | None
