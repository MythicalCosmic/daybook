"""Celery tasks of payroll, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

import logging

from celery import shared_task
from django.utils import translation

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payslip_pdf(self, payslip_id: int) -> bool:
    """The published payslip's PDF, in the person's language, to them in the employee bot."""
    from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError

    from apps.notifications import telegram
    from apps.notifications.telegram import BotName
    from apps.payroll import payslip_pdf, queries
    from apps.payroll.models import Payslip

    payslip = (
        Payslip.objects.select_related("membership__user", "run", "company")
        .filter(pk=payslip_id, published_at__isnull=False)
        .first()
    )
    if payslip is None:
        return False
    user = payslip.membership.user
    if not user.telegram_id or payslip.membership.status != "approved":
        return False
    language = user.language or "uz"
    stored = payslip_pdf.save(payslip, language=language)
    with translation.override(language):
        caption = queries.month_label(payslip.run.period)
    try:
        telegram.send_document(
            BotName.EMPLOYEE,
            user.telegram_id,
            stored.name,
            storage="private",
            caption=caption,
            filename=payslip_pdf.file_name(payslip),
        )
    except TelegramForbiddenError:
        return False
    except TelegramNetworkError as exc:
        raise self.retry(exc=exc) from exc
    return True


@shared_task
def prepare_runs() -> int:
    """Hourly: on the 1st after 06:00 local, last month's draft run for each company with
    `auto_prepare`, calculated, and the finalizers told."""
    from apps.payroll import jobs

    return jobs.prepare_runs()


@shared_task
def pay_day_reminders() -> int:
    """Hourly: on pay day morning, a month not paid yet reaches the payers."""
    from apps.payroll import jobs

    return jobs.pay_day_reminders()


@shared_task
def evaluate_daily_rules() -> int:
    """Hourly (acts once a company day, after attendance closed yesterday): daily rules."""
    from apps.payroll import jobs

    return jobs.evaluate_daily_rules()
