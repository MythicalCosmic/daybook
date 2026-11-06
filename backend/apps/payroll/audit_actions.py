"""Audit action codes and labels of payroll (`apps.audit.registry.register`).

Every row that shows an amount of someone's pay is readable only with `payroll.view`
(`services._audit` stamps `required_perm`). Pay changes, decided bonuses and fines, advances
and payslips are audited on the person (target `membership`), so they appear on their History
timeline as well.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PayrollAction(models.TextChoices):
    SETTINGS_CHANGED = "payroll.settings_changed", _("Changed payroll settings")
    PAY_SET = "payroll.pay_set", _("Set someone's pay")
    PAY_CHANGED = "payroll.pay_changed", _("Corrected someone's pay setup")
    PAY_REMOVED = "payroll.pay_removed", _("Removed a pay setup")
    TASK_RATE_SAVED = "payroll.task_rate_saved", _("Saved a task rate")
    TASK_RATE_REMOVED = "payroll.task_rate_removed", _("Removed a task rate")
    RULE_SAVED = "payroll.rule_saved", _("Saved a bonus or fine rule")
    RULE_REMOVED = "payroll.rule_removed", _("Removed a bonus or fine rule")
    ADJUSTMENT_PROPOSED = "payroll.adjustment_proposed", _("Proposed a bonus or fine")
    ADJUSTMENT_APPROVED = "payroll.adjustment_approved", _("Approved a bonus or fine")
    ADJUSTMENT_REJECTED = "payroll.adjustment_rejected", _("Rejected a bonus or fine")
    ADJUSTMENT_VOIDED = "payroll.adjustment_voided", _("Voided a bonus or fine")
    ADJUSTMENT_DISPUTED = "payroll.adjustment_disputed", _("Disputed a fine")
    DISPUTE_ANSWERED = "payroll.dispute_answered", _("Answered a disputed fine")
    ADVANCE_REQUESTED = "payroll.advance_requested", _("Asked for an advance")
    ADVANCE_APPROVED = "payroll.advance_approved", _("Approved an advance")
    ADVANCE_REJECTED = "payroll.advance_rejected", _("Rejected an advance")
    ADVANCE_CANCELLED = "payroll.advance_cancelled", _("Cancelled an advance")
    ADVANCE_PAID = "payroll.advance_paid", _("Paid an advance")
    ADVANCE_REPAID = "payroll.advance_repaid", _("Recorded an advance paid back")
    RUN_CREATED = "payroll.run_created", _("Started a payroll run")
    RUN_CALCULATED = "payroll.run_calculated", _("Calculated a payroll run")
    RUN_FINALIZED = "payroll.run_finalized", _("Finalized a payroll run")
    RUN_REOPENED = "payroll.run_reopened", _("Reopened a payroll run")
    RUN_CANCELLED = "payroll.run_cancelled", _("Cancelled a payroll run")
    FINAL_RUN_CREATED = "payroll.final_run_created", _("Prepared a final payslip for a leaver")
    LEAVE_PAYOUT_CHANGED = "payroll.leave_payout_changed", _("Changed the unused leave paid out")
    PAYSLIPS_PUBLISHED = "payroll.payslips_published", _("Published payslips")
    PAYSLIPS_PAID = "payroll.payslips_paid", _("Marked payslips paid")
    PAYSLIP_LINE_ADDED = "payroll.payslip_line_added", _("Added a line to a payslip")
    PAYSLIP_LINE_REMOVED = "payroll.payslip_line_removed", _("Removed a line from a payslip")
    PAYSLIP_RECEIVED = "payroll.payslip_received", _("Confirmed a salary was received")
