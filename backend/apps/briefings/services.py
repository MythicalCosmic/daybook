"""Business logic of briefings: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`. Writing and sending
the reviews themselves is `apps.briefings.reviews` (the beat and the advisor agent use it).

    request_regenerate(member, kind="weekly")   the caller's latest review written again now
    update_settings(company, by=member, changes={"weekday": 4})
    mark_opened(briefing, member)
"""

from datetime import datetime, time
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.briefings import conf, periods, reviews, scope, tasks
from apps.briefings.audit_actions import BriefingAction
from apps.briefings.models import Briefing, BriefingSettings
from apps.console.base import bump
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.permissions import Perm

REGENERATE_PER_DAY = 3
SETTINGS_FIELDS = ("weekly_enabled", "monthly_enabled", "weekday", "send_at", "recipients")


def _ensure_settings_perm(by: Membership) -> None:
    if not by.has_perm(Perm.COMPANY_SETTINGS):
        raise PermissionDenied(_("You can't change the business reviews."))


def regenerated_today(company, now: datetime) -> int:
    from apps.audit.models import AuditLog

    zone = ZoneInfo(company.timezone)
    start = datetime.combine(reviews.local(company, now).date(), time.min, zone)
    return AuditLog.objects.filter(
        company_id=company.pk, action=BriefingAction.REGENERATED, created_at__gte=start
    ).count()


@transaction.atomic
def request_regenerate(
    by: Membership, *, kind: str = Briefing.Kind.WEEKLY, now: datetime | None = None
) -> Briefing | None:
    """The caller's latest review of `kind` written again now, at most REGENERATE_PER_DAY times
    a day per company: from the templates at once (the review comes back), or by Claude on the
    ai queue (None: it is on its way, the page hears of it through the pulse)."""
    _ensure_settings_perm(by)
    now = now or timezone.now()
    company = by.company
    if regenerated_today(company, now) >= REGENERATE_PER_DAY:
        raise DomainError(
            _("That's all for today (%(limit)s): write it again tomorrow.")
            % {"limit": REGENERATE_PER_DAY}
        )
    if not scope.of(by).has_data:
        raise DomainError(_("There is nothing for a business review in what you can see."))
    period = periods.latest(kind, reviews.local(company, now).date())
    audit.record(
        BriefingAction.REGENERATED,
        company_id=company.pk,
        actor=by.user,
        target=conf.get_settings(company),
        kind=kind,
        day=period.start.isoformat(),
    )
    if reviews.claude_writes(company):
        transaction.on_commit(partial(tasks.regenerate.delay, by.pk, kind))
        return None
    return reviews.regenerate_for(by, kind, now, use_ai=False)


def mark_opened(briefing: Briefing, member: Membership, now: datetime | None = None) -> None:
    reviews.opened(briefing, member, now or timezone.now())


@transaction.atomic
def update_settings(company, *, by: Membership, changes: dict) -> BriefingSettings:
    """When the reviews go out and to whom. Maslahatchi's next run follows the new times."""
    _ensure_settings_perm(by)
    row = BriefingSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    unknown = set(changes) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValidationError({name: [_("Unknown setting.")] for name in sorted(unknown)})
    before = {name: audit.plain(getattr(row, name)) for name in SETTINGS_FIELDS}
    for name, value in changes.items():
        setattr(row, name, value)
    row.full_clean(exclude=["company"])
    row.save()
    after = {name: audit.plain(getattr(row, name)) for name in SETTINGS_FIELDS}
    if changed := audit.diff(before, after):
        audit.record(
            BriefingAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=row,
            changes=changed,
        )
        from apps.ai.agents import advisor

        advisor.reschedule(company)
        bump(company.pk, reviews.PULSE)
    return row
