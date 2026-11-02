"""Words for payslip lines and run warnings, in the reader's language.

Lines and warnings keep a `code` and their numbers in `params`; the text is written when it is
read (API, PDF, bot), so an Uzbek employee and a Russian accountant each read their own. A
line a person typed (`manual`, a bonus's reason) keeps its own words.
"""

from decimal import Decimal

from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.payroll import queries
from apps.payroll.models import Adjustment, PayslipLine, PayType

Kind = PayslipLine.Kind


def _hours(minutes) -> str:
    hours = Decimal(int(minutes or 0)) / Decimal(60)
    text = f"{hours:.1f}".rstrip("0").rstrip(".")
    return text.replace(".", "," if (translation.get_language() or "en")[:2] != "en" else ".")


def _days(count) -> str:
    count = int(count or 0)
    return ngettext("%(count)s day", "%(count)s days", count) % {"count": count}


def _leave_kind(kind: str) -> str:
    return {
        "annual": _("Annual leave"),
        "sick": _("Sick leave"),
        "unpaid": _("Unpaid leave"),
        "study": _("Study leave"),
        "maternity": _("Maternity leave"),
        "day_off": _("Day off"),
    }.get(kind, _("Leave"))


def line_label(line: PayslipLine) -> str:
    params = line.params or {}
    code = params.get("code", "")
    if line.kind == Kind.MANUAL or code == "manual":
        return line.label
    if code == "base":
        pay_type = params.get("pay_type")
        if pay_type == PayType.MONTHLY:
            if "days" in params and "scheduled" in params and params.get("from"):
                return _("Monthly pay for %(days)s of %(scheduled)s working days") % params
            if (
                params.get("calendar_days")
                and "days" in params
                and params["days"] != params.get("calendar_days")
            ):
                return _("Monthly pay for %(days)s of %(calendar_days)s calendar days") % params
            return _("Monthly pay")
        if pay_type == PayType.DAILY:
            return _("Days worked: %(days)s") % {"days": _days(params.get("days"))}
        if pay_type == PayType.HOURLY:
            return _("Hours worked: %(hours)s") % {"hours": _hours(params.get("minutes"))}
        return str(Kind.BASE.label)
    if code == "absent":
        return _("Absent: %(days)s") % {"days": _days(params.get("days"))}
    if code == "not_employed":
        return _("Not employed on those days: %(days)s") % {"days": _days(params.get("days"))}
    if code == "unpaid_leave":
        return _("Unpaid leave: %(days)s") % {"days": _days(params.get("days"))}
    if code == "suspended":
        return _("Suspended without pay: %(days)s") % {"days": _days(params.get("days"))}
    if code == "partial_leave":
        return _("%(leave)s at %(percent)s%%: %(days)s") % {
            "leave": _leave_kind(params.get("leave_kind")),
            "percent": params.get("percent"),
            "days": _days(params.get("days")),
        }
    if code == "paid_leave":
        return _("%(leave)s at %(percent)s%%: %(days)s") % {
            "leave": _leave_kind(params.get("leave_kind")),
            "percent": params.get("percent"),
            "days": _days(params.get("days")),
        }
    if code == "overtime":
        return _("Overtime: %(hours)s h at ×%(multiplier)s") % {
            "hours": _hours(params.get("minutes")),
            "multiplier": params.get("multiplier", ""),
        }
    if code == "night_work":
        return _("Night hours: %(hours)s h at ×%(multiplier)s") % {
            "hours": _hours(params.get("minutes")),
            "multiplier": params.get("multiplier", ""),
        }
    if code == "holiday_work":
        return _("Work on holidays at ×%(multiplier)s") % {"multiplier": params.get("multiplier")}
    if code == "piece":
        count = int(params.get("tasks") or 0)
        tasks = ngettext("%(count)s task", "%(count)s tasks", count) % {"count": count}
        if params.get("routine"):
            return _("Task pay: %(routine)s, %(tasks)s") % {
                "routine": params["routine"],
                "tasks": tasks,
            }
        return _("Task pay: %(tasks)s") % {"tasks": tasks}
    if code == "task_reward":
        return _("Reward for a task: %(title)s") % {"title": params.get("title", "")}
    if code == "adjustment":
        kind = Adjustment.Kind(line.adjustment.kind).label if line.adjustment_id else line.kind
        reason = params.get("reason") or line.label
        text = f"{kind}: {reason}" if reason else str(kind)
        if params.get("capped"):
            text += " " + _("(capped, of %(full)s)") % {
                "full": queries.money_text(Decimal(params["full"]), line.payslip.currency)
            }
        return text
    if code == "advance":
        return _("Advance repaid")
    if code == "reimbursement":
        if params.get("what"):
            return _("Expenses paid back: %(what)s") % {"what": params["what"]}
        return str(Kind.REIMBURSEMENT.label)
    if code == "income_tax":
        return _("Income tax, %(percent)s%%") % {"percent": params.get("percent")}
    if code == "inps":
        return _("Pension contribution, %(percent)s%%") % {"percent": params.get("percent")}
    if code == "rounding":
        return str(Kind.ROUNDING.label)
    return line.label or str(Kind(line.kind).label)


def warning_text(warning: dict) -> str:
    code = warning.get("code")
    name = (warning.get("member") or {}).get("name", "")
    count = warning.get("count", 0)
    if code == "no_pay_setup":
        return _("%(name)s has no pay setup: no payslip.") % {"name": name}
    if code == "proposed":
        return ngettext(
            "%(count)s bonus or fine still waits for a decision.",
            "%(count)s bonuses or fines still wait for a decision.",
            count,
        ) % {"count": count}
    if code == "disputes":
        return ngettext(
            "%(count)s disputed fine has no answer yet.",
            "%(count)s disputed fines have no answer yet.",
            count,
        ) % {"count": count}
    if code == "pending_overtime":
        return ngettext(
            "%(count)s overtime record waits for approval: unpaid until approved.",
            "%(count)s overtime records wait for approval: unpaid until approved.",
            count,
        ) % {"count": count}
    if code == "open_attendance":
        return ngettext(
            "%(count)s person is still checked in.",
            "%(count)s people are still checked in.",
            count,
        ) % {"count": count}
    if code == "no_usd_rate":
        return _("%(name)s is paid in dollars and there is no dollar rate: no payslip.") % {
            "name": name
        }
    if code == "deductions_capped":
        return _("Fines of %(name)s are capped at %(percent)s%% of the pay.") % {
            "name": name,
            "percent": warning.get("percent"),
        }
    if code == "advance_reduced":
        return _("%(name)s earned too little to repay the advance in full this month.") % {
            "name": name
        }
    if code == "negative_net":
        return _("The pay of %(name)s is below zero: lower a deduction.") % {"name": name}
    if code == "no_scheduled_days":
        return _("%(name)s has no working days this month: paid by calendar days.") % {"name": name}
    return code or ""
