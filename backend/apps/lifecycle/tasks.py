"""Celery tasks of the people lifecycle, queued with `transaction.on_commit`, and the jobs Celery
beat runs (apps/lifecycle/beat.py).

Thin wrappers: services import this module to queue jobs, so it never imports them at the top;
the work itself lives in plain modules (`notify`, `terminations`, `job_changes`).
"""

from celery import shared_task


@shared_task
def notify_record_issued(record_id: int) -> None:
    """The person hears a record was given to them, with a way into the app."""
    from apps.lifecycle import notify

    notify.record_issued(record_id)


@shared_task
def notify_explanation(record_id: int) -> None:
    """Whoever gave the record hears the person explained."""
    from apps.lifecycle import notify

    notify.explanation(record_id)


# Leaving -------------------------------------------------------------------------------------


@shared_task
def notify_leave_requested(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.leave_requested(termination_id)


@shared_task
def notify_leave_agreed(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.leave_agreed(termination_id)


@shared_task
def notify_leave_declined(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.leave_declined(termination_id)


@shared_task
def notify_leave_withdrawn(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.leave_withdrawn(termination_id)


@shared_task
def notify_left(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.left(termination_id)


@shared_task
def notify_last_day(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.last_day(termination_id)


@shared_task
def notify_leave_failed(termination_id: int) -> None:
    from apps.lifecycle import notify

    notify.leave_failed(termination_id)


@shared_task
def run_leaving() -> int:
    """Every 15 minutes: the morning note of a last day, and the evening it is over."""
    from apps.lifecycle import terminations

    terminations.remind_due()
    return terminations.complete_due()


# Job changes ---------------------------------------------------------------------------------


@shared_task
def notify_change_proposed(change_id: int) -> None:
    from apps.lifecycle import notify

    notify.change_proposed(change_id)


@shared_task
def notify_change_decided(change_id: int) -> None:
    from apps.lifecycle import notify

    notify.change_decided(change_id)


@shared_task
def notify_change_applied(change_id: int) -> None:
    from apps.lifecycle import notify

    notify.changed(change_id)


@shared_task
def notify_change_failed(change_id: int) -> None:
    from apps.lifecycle import notify

    notify.change_failed(change_id)


@shared_task
def apply_job_changes() -> int:
    """Every 15 minutes: approved job changes whose day has come take effect."""
    from apps.lifecycle import job_changes

    return job_changes.apply_due()


# Performance reviews (apps.lifecycle.reviews, review_notify) ----------------------------------


@shared_task
def notify_review_round_opened(cycle_id: int) -> None:
    """Everyone in a round that opened hears, with a way into the app."""
    from apps.lifecycle import review_notify

    review_notify.round_opened(cycle_id)


@shared_task
def notify_review_stage(cycle_id: int) -> None:
    """The reviewers hear their part has begun, with how many wait for them."""
    from apps.lifecycle import review_notify

    review_notify.reviewers_part(cycle_id)


@shared_task
def notify_review_reminders(cycle_id: int) -> None:
    """The day before a deadline: whoever is still to answer (or to publish) hears again."""
    from apps.lifecycle import review_notify

    review_notify.deadline_reminders(cycle_id)


@shared_task
def notify_review_nudge(cycle_id: int, review_ids: list[int], reviewer_ids: list[int]) -> None:
    """The round page's Remind: the people still to answer, the reviewers still to publish."""
    from apps.lifecycle import review_notify

    review_notify.nudge(cycle_id, review_ids, reviewer_ids)


@shared_task
def notify_review_published(review_id: int) -> None:
    from apps.lifecycle import review_notify

    review_notify.published(review_id)


@shared_task
def run_reviews() -> int:
    """Every 15 minutes: the day-before reminders, and the reviewers' part after the self
    deadline, in each company's time."""
    from apps.lifecycle import reviews

    return reviews.run_due()
