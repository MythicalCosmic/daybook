"""Audit action codes and labels of the finance ledger (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class FinanceAction(models.TextChoices):
    ACCOUNT_CREATED = "finance.account_created", _("Added a money account")
    ACCOUNT_REOPENED = "finance.account_reopened", _("Reopened a money account")
    TRANSACTION_RECORDED = "finance.transaction_recorded", _("Recorded a ledger entry")
    TRANSACTION_APPROVED = "finance.transaction_approved", _("Approved a ledger entry")
    TRANSACTION_REJECTED = "finance.transaction_rejected", _("Rejected a ledger entry")
    TRANSACTION_VOIDED = "finance.transaction_voided", _("Voided a ledger entry")
    TRANSFER_MADE = "finance.transfer_made", _("Moved money between accounts")
    TRANSFER_VOIDED = "finance.transfer_voided", _("Voided a transfer")
    DEBT_OPENED = "finance.debt_opened", _("Recorded a debt")
    DEBT_PAID = "finance.debt_paid", _("Recorded a debt payment")
    DEBT_WRITTEN_OFF = "finance.debt_written_off", _("Wrote off a debt")
    DEBT_CANCELLED = "finance.debt_cancelled", _("Cancelled a debt")
