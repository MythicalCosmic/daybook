"""Audit action codes and labels of the finance ledger (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class FinanceAction(models.TextChoices):
    ACCOUNT_CREATED = "finance.account_created", _("Added a money account")
    ACCOUNT_REOPENED = "finance.account_reopened", _("Reopened a money account")
    ACCOUNT_UPDATED = "finance.account_updated", _("Changed a money account")
    ACCOUNT_ARCHIVED = "finance.account_archived", _("Archived a money account")
    TRANSACTION_RECORDED = "finance.transaction_recorded", _("Recorded a ledger entry")
    TRANSACTION_UPDATED = "finance.transaction_updated", _("Changed a ledger entry")
    TRANSACTION_APPROVED = "finance.transaction_approved", _("Approved a ledger entry")
    TRANSACTION_REJECTED = "finance.transaction_rejected", _("Rejected a ledger entry")
    TRANSACTION_VOIDED = "finance.transaction_voided", _("Voided a ledger entry")
    RECEIPT_ADDED = "finance.receipt_added", _("Attached a receipt")
    RECEIPT_REMOVED = "finance.receipt_removed", _("Removed a receipt")
    TRANSFER_MADE = "finance.transfer_made", _("Moved money between accounts")
    TRANSFER_VOIDED = "finance.transfer_voided", _("Voided a transfer")
    DEBT_OPENED = "finance.debt_opened", _("Recorded a debt")
    DEBT_UPDATED = "finance.debt_updated", _("Changed a debt")
    DEBT_PAID = "finance.debt_paid", _("Recorded a debt payment")
    DEBT_WRITTEN_OFF = "finance.debt_written_off", _("Wrote off a debt")
    DEBT_CANCELLED = "finance.debt_cancelled", _("Cancelled a debt")
    INSTALLMENTS_SET = "finance.installments_set", _("Set an instalment plan")
    CATEGORY_CREATED = "finance.category_created", _("Added a finance category")
    CATEGORY_UPDATED = "finance.category_updated", _("Changed a finance category")
    CATEGORY_MOVED = "finance.category_moved", _("Moved a finance category")
    CATEGORY_MERGED = "finance.category_merged", _("Merged finance categories")
    CATEGORY_DELETED = "finance.category_deleted", _("Deleted a finance category")
    COUNTERPARTY_CREATED = "finance.counterparty_created", _("Added a counterparty")
    COUNTERPARTY_UPDATED = "finance.counterparty_updated", _("Changed a counterparty")
    RATE_SET = "finance.rate_set", _("Set an exchange rate")
    RATE_DELETED = "finance.rate_deleted", _("Removed an exchange rate")
    PERIOD_LOCKED = "finance.period_locked", _("Closed the books for a period")
    PERIOD_REOPENED = "finance.period_reopened", _("Reopened a closed period")
    SETTINGS_UPDATED = "finance.settings_updated", _("Changed finance settings")
    BALANCES_FIXED = "finance.balances_fixed", _("Corrected balances from the ledger")
