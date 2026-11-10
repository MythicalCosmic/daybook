"""Celery tasks of HR records, queued with `transaction.on_commit` or run by beat.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import (`notify`, `watch`).
"""

from celery import shared_task


@shared_task
def notify_contract_ready(contract_id: int) -> None:
    """The person hears their contract is in force and can be read in the app."""
    from apps.hr import notify

    notify.contract_ready(contract_id)


@shared_task
def watch_expiries() -> int:
    """Documents, contracts and probations reaching a warning step → HR (once per step)."""
    from apps.hr import watch

    return watch.watch_expiries()


@shared_task
def watch_coverage() -> int:
    """Pharmacies open with nobody qualified checked in, and tills opened by someone who isn't
    a qualified pharmacist → the branch manager and the owners (once each)."""
    from apps.hr import watch

    return watch.watch_coverage()


@shared_task
def watch_planned_coverage() -> int:
    """Gaps in the published roster of the coming days → who runs the roster (once per gap)."""
    from apps.hr import watch

    return watch.watch_planned_coverage()


@shared_task
def post_celebrations() -> int:
    """Today's birthdays and work anniversaries → the groups and the person (once each)."""
    from apps.hr import watch

    return watch.post_celebrations()


# Policies (apps.hr.policies) ----------------------------------------------------------------


@shared_task
def follow_up_policies() -> int:
    """Newcomers asked to sign, notices, reminders before the deadline and late notes to the
    manager (once each, outside quiet hours)."""
    from apps.hr.policies import follow_up

    return follow_up.follow_up()


@shared_task
def policy_notices(policy_id: int) -> int:
    """After a publish: the people asked hear (now, or after the quiet hours)."""
    from apps.hr.policies import follow_up

    return follow_up.notices_after_publish(policy_id)


@shared_task
def policy_to_read(policy_id: int, version_id: int) -> int:
    """A policy that asks no signature: its readers hear about the new version."""
    from apps.hr.policies import follow_up

    return follow_up.to_read(policy_id, version_id)


@shared_task
def policies_after_joining(company_id: int) -> int:
    """Someone was approved: the policies of their position and branches ask them."""
    from apps.hr.policies import follow_up

    return follow_up.after_joining(company_id)
