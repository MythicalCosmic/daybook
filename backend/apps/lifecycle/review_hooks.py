"""Registrations of performance reviews with the shared registries, imported by `hooks.py` (so
by `AppConfig.ready()`): what the person and the reviewer hear, the sidebar badge of reviews to
write and the pages' version key, the deadlines on the company calendar, and the export."""

from django.utils.translation import gettext_lazy as _

from apps.console import registry
from apps.exports.registry import register_exporter
from apps.inbox.registry import register_kind
from apps.lifecycle import review_notify, review_queries, reviews
from apps.members.permissions import Perm

FEATURE = "hr"

# The person (the employee bot, into the mini app) and the reviewer (the dashboard, the owner
# bot).
register_kind(
    review_notify.REVIEW,
    label=_("Your performance reviews"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    review_notify.TO_WRITE,
    label=_("Performance reviews to write"),
    audience="owner",
    default_telegram=True,
)

registry.register_pulse(reviews.PULSE, perm=Perm.REVIEWS_MANAGE, count=None, feature=FEATURE)
registry.register_pulse(
    reviews.TO_WRITE,
    perm=Perm.REVIEWS_MANAGE,
    count=review_queries.to_write_count,
    feature=FEATURE,
)

registry.register_calendar_source(
    "lifecycle.review_deadlines",
    label=_("Performance review deadlines"),
    perm=Perm.REVIEWS_MANAGE,
    events=review_queries.calendar_deadlines,
    feature=FEATURE,
)

register_exporter(
    "lifecycle.reviews",
    perm=Perm.REVIEWS_MANAGE,
    label=_("Performance reviews"),
    columns=[
        ("round", _("Round")),
        ("person", _("Employee")),
        ("position", _("Position")),
        ("branch", _("Branch")),
        ("reviewer", _("Reviewer")),
        ("self_sent_at", _("Self review sent"), "datetime"),
        ("self_average", _("Self rating (average)"), "number"),
        ("manager_average", _("Reviewer's rating (average)"), "number"),
        ("rating", _("Overall rating"), "number"),
        ("outcome", _("Outcome")),
        ("raise_percent", _("Raise (percent)"), "number"),
        ("promotion", _("Promoted to")),
        ("bonus", _("Bonus"), "money"),
        ("effective_on", _("From"), "date"),
        ("state", _("Approval")),
        ("published_at", _("Published"), "datetime"),
        ("acknowledged_at", _("Read by the employee"), "datetime"),
    ],
    rows=review_queries.export_rows,
    sensitive=True,
    feature=FEATURE,
)
