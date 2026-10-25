"""Registrations with the shared registries and signal receivers of attendance.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.attendance import actions, bot_messages, defaults, providers, queries, services
from apps.attendance.audit_actions import AttendanceAction
from apps.audit import registry as audit_registry
from apps.companies.signals import company_created
from apps.console import registry
from apps.core.files import register_file_check
from apps.exports.registry import register_exporter
from apps.inbox.registry import register_action, register_kind
from apps.members import bot_menu, scope
from apps.members.permissions import Perm
from apps.members.signals import member_left
from apps.tasks import offdays
from apps.timeoff.signals import time_off_approved, time_off_cancelled

VIEW, MANAGE = Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE
FEATURE = "attendance"

audit_registry.register(AttendanceAction)


def _record_in_scope(member, record_id) -> bool:
    from apps.attendance.models import AttendanceRecord

    record = AttendanceRecord.objects.filter(company_id=member.company_id, pk=record_id).first()
    return record is not None and scope.allows(scope.branch_ids(member), record.branch_id)


def _shift_in_scope(member, shift_id) -> bool:
    from apps.attendance.models import WorkShift

    shift = WorkShift.objects.filter(company_id=member.company_id, pk=shift_id).first()
    return shift is not None and scope.allows(scope.branch_ids(member), shift.branch_id)


audit_registry.register_target("attendancerecord", VIEW, check=_record_in_scope)
audit_registry.register_target("workshift", VIEW, check=_shift_in_scope)
audit_registry.register_target("workschedule", VIEW)

# Sidebar badges and version keys.
registry.register_pulse("attendance.not_in", perm=VIEW, count=queries.not_in_count, feature=FEATURE)
registry.register_pulse("attendance.swaps", perm=MANAGE, count=queries.swaps_count, feature=FEATURE)
registry.register_pulse(
    "attendance.corrections", perm=MANAGE, count=queries.corrections_count, feature=FEATURE
)
registry.register_pulse("attendance.board", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("attendance.roster", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("attendance.schedules", perm=VIEW, count=None, feature=FEATURE)
registry.register_pulse("attendance.settings", perm=MANAGE, count=None, feature=FEATURE)

# Needs you.
registry.register_queue(
    "attendance.corrections",
    perm=MANAGE,
    label=_("Attendance corrections"),
    count=lambda member: queries.pending_corrections(member).count(),
    items=providers.correction_items,
    feature=FEATURE,
)
registry.register_queue(
    "attendance.overtime",
    perm=MANAGE,
    label=_("Overtime to approve"),
    count=lambda member: queries.pending_overtime(member).count(),
    items=providers.overtime_items,
    feature=FEATURE,
)
registry.register_queue(
    "attendance.swaps",
    perm=MANAGE,
    label=_("Shift swaps"),
    count=queries.swaps_count,
    items=providers.swap_items,
    feature=FEATURE,
)

# Overview, branch cards, briefings, the team directory, the portfolio.
registry.register_stream("attendance.checked_in", perm=VIEW, fetch=queries.stream, feature=FEATURE)
registry.register_branch_facts("attendance", perm=VIEW, facts=queries.branch_facts, feature=FEATURE)
registry.register_brief_section(
    "attendance", perm=VIEW, order=30, build=queries.brief_section, feature=FEATURE
)
registry.register_person_fields(
    "attendance", perm=VIEW, fetch=queries.person_fields, feature=FEATURE
)
registry.register_company_facts(
    "attendance", perm=VIEW, facts=queries.company_facts, feature=FEATURE
)
registry.register_offboard_step(
    "attendance",
    perm=MANAGE,
    order=30,
    label=_("Shifts and attendance"),
    preview=providers.offboard_preview,
    feature=FEATURE,
)
registry.register_setup_step(
    "attendance.schedules",
    perm=MANAGE,
    order=80,
    label=_("Schedules"),
    description=_("Set working hours so attendance knows who is expected when."),
    url="attendance/schedules",
    done=providers.setup_done,
    feature=FEATURE,
)
registry.register_calendar_source(
    "attendance.shifts",
    label=_("Shifts"),
    perm=None,
    events=providers.calendar_events,
    feature=FEATURE,
)
registry.register_copy_part(
    "attendance.setup",
    label=_("Work schedules and shift templates"),
    perm=MANAGE,
    copy=providers.copy_setup,
    feature=FEATURE,
)

register_exporter(
    "attendance.timesheet",
    perm=VIEW,
    label=_("Attendance timesheet"),
    columns=providers.TIMESHEET_COLUMNS,
    rows=providers.timesheet_rows,
    params=providers.TimesheetExportParams,
    feature=FEATURE,
)

register_file_check("attendance.selfie", providers.selfie_check)

# Notifications: approvals live in Needs you (their Telegram copy carries the buttons).
register_kind(
    "attendance.correction",
    label=_("Attendance corrections to approve"),
    audience="owner",
    default_telegram=True,
    queue_kind="attendance.corrections",
)
register_action("attendance.correction", "approve", actions.approve_correction)
register_action("attendance.correction", "reject", actions.reject_correction)
register_kind(
    "attendance.overtime",
    label=_("Overtime to approve"),
    audience="owner",
    default_telegram=True,
    queue_kind="attendance.overtime",
)
register_action("attendance.overtime", "approve", actions.approve_overtime)
register_action("attendance.overtime", "reject", actions.reject_overtime)
register_kind(
    "attendance.swap",
    label=_("Shift swaps to approve"),
    audience="owner",
    default_telegram=True,
    queue_kind="attendance.swaps",
)
register_action("attendance.swap", "approve", actions.approve_swap)
register_action("attendance.swap", "reject", actions.reject_swap)
register_kind(
    "attendance.no_show",
    label=_("Someone hasn't checked in"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    "attendance.outside",
    label=_("Check-ins outside the branch"),
    audience="owner",
    default_telegram=False,
)
register_kind(
    "attendance.cover_request",
    label=_("A colleague asks you to cover a shift"),
    audience="employee",
    default_telegram=True,
)
register_action("attendance.cover_request", "accept", actions.accept_cover)
register_action("attendance.cover_request", "decline", actions.decline_cover)
register_kind(
    "attendance.open_shift",
    label=_("Open shifts you can take"),
    audience="employee",
    default_telegram=True,
)
register_action("attendance.open_shift", "claim", actions.claim_shift)
register_kind(
    "attendance.roster", label=_("Your shifts"), audience="employee", default_telegram=True
)
register_kind(
    "attendance.decision",
    label=_("Answers to your attendance requests"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    "attendance.auto_closed",
    label=_("Forgotten check-outs"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)

# "Keldim / Ketdim" in the employee bot's menu (opens the mini app's check-in when it has
# an https address; otherwise the bot asks for a location share).
bot_menu.register_menu_button(
    bot_messages.MENU_CHECK,
    order=10,
    visible=lambda member: member.company.has_feature(FEATURE),
    web_app_screen=bot_messages.APP_SCREEN,
)

# "Tasks follow shifts": no daily tasks on a rostered day off (when the setting is on).
offdays.register(queries.off_day_people)


def make_defaults(sender, company, by=None, **kwargs) -> None:
    defaults.ensure(company)


def on_time_off_approved(sender, time_off, by=None, **kwargs) -> None:
    if time_off.company.has_feature(FEATURE):
        services.time_off_approved(time_off)


def on_time_off_cancelled(sender, time_off, by=None, previous_status=None, **kwargs) -> None:
    if time_off.company.has_feature(FEATURE):
        services.time_off_cancelled(time_off, previous_status)


def on_member_left(sender, membership, by=None, **kwargs) -> None:
    services.member_left(membership, by=by)


company_created.connect(make_defaults, dispatch_uid="attendance.make_defaults")
time_off_approved.connect(on_time_off_approved, dispatch_uid="attendance.time_off_approved")
time_off_cancelled.connect(on_time_off_cancelled, dispatch_uid="attendance.time_off_cancelled")
member_left.connect(on_member_left, dispatch_uid="attendance.member_left")
