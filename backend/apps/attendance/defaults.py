"""Default rows of attendance for a company."""

from datetime import time

from django.utils import translation
from django.utils.translation import gettext as _

from apps.attendance.models import ShiftTemplate

# (name, start, end, break minutes, colour slot): the roster builder's ready-made shifts.
TEMPLATES = (
    ("Morning", time(9, 0), time(18, 0), 60, 1),
    ("Evening", time(14, 0), time(23, 0), 60, 3),
    ("Full day", time(9, 0), time(21, 0), 90, 4),
    ("Night", time(22, 0), time(7, 0), 60, 5),
)


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from the `company_created`
    receiver and from `manage.py ensure_company_defaults` after every deploy.

    The shift templates are made only for a company that never had any (removed templates
    are kept as inactive rows), so a deploy never brings back what an owner deleted."""
    if ShiftTemplate.objects.filter(company=company).exists():
        return
    with translation.override(company.default_language):
        names = {
            "Morning": _("Morning"),
            "Evening": _("Evening"),
            "Full day": _("Full day"),
            "Night": _("Night"),
        }
        ShiftTemplate.objects.bulk_create(
            ShiftTemplate(
                company=company,
                name=names[name],
                starts_at=starts,
                ends_at=ends,
                break_minutes=pause,
                color=color,
                order=index,
            )
            for index, (name, starts, ends, pause, color) in enumerate(TEMPLATES)
        )
