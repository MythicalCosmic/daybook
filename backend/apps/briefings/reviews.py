"""Writing and sending the business reviews (docs/PLAN-OWNER.md §3.15, §8.5): a plain module,
so `services`, `tasks` and the advisor agent can all use it.

    run_scheduled(company, "weekly", now, use_ai=True)    # Maslahatchi's run (apps.ai.agents)
    tick(now)                                             # the beat, for everyone else

A review is written once per reading scope and language (apps.briefings.scope): its facts first
(apps.briefings.facts, the only source of its numbers), then its words, by Claude through the
advisor agent when it may (its draft checked against the facts) or else from the templates
(apps.briefings.writing); each reader gets it once (`BriefingDelivery`), in the owner bot when
they use it, with the review's page behind its Open button. Where AI is on and Maslahatchi
works, its own run sends the reviews; the beat sends them everywhere else (and, as a safety
net, where Maslahatchi's run is an hour late).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.briefings import conf, display, facts, periods, scope, writing
from apps.briefings.models import Briefing, BriefingDelivery, BriefingSettings
from apps.companies.models import Company, Feature
from apps.console.base import bump
from apps.core.exceptions import DomainError
from apps.members.models import Membership

logger = logging.getLogger(__name__)

PULSE = "briefings"
KINDS = (Briefing.Kind.WEEKLY, Briefing.Kind.MONTHLY)
# The inbox kinds of the two reviews (apps.briefings.hooks).
NOTIFY_KIND = {Briefing.Kind.WEEKLY: "briefings.weekly", Briefing.Kind.MONTHLY: "briefings.monthly"}
# Companies without any of these have nothing to review.
DATA_FEATURES = (Feature.FINANCE, Feature.SALES, Feature.STOCK, Feature.ATTENDANCE)
# The beat sends a review Maslahatchi should have sent when it is this late.
ADVISOR_GRACE = timedelta(hours=1)


@dataclass
class Outcome:
    """What one run did: reviews written (and how many by Claude), people they went to."""

    reviews: int = 0
    by_ai: int = 0
    sent: int = 0


def local(company, now: datetime) -> datetime:
    return timezone.localtime(now, ZoneInfo(company.timezone))


def page_url(briefing: Briefing) -> str:
    return f"/c/{briefing.company_id}/ai/advisor?review={briefing.pk}"


# Writing -----------------------------------------------------------------------------------------


def advisor_writes(company) -> bool:
    """Maslahatchi writes the reviews here: AI is on and the advisor agent works and is on."""
    from apps.ai import conf as ai_conf
    from apps.ai.agents import advisor

    return ai_conf.ai_on(company) and advisor.is_on(company)


def claude_writes(company) -> bool:
    """Claude would write a review here now (not only the templates)."""
    from apps.ai import availability

    return (
        advisor_writes(company)
        and availability.status(company).available
        and not availability.fake()
    )


def write_content(company, review_facts: dict, language: str, *, use_ai: bool):
    """(content, written_by, model): Claude's checked draft when `use_ai` and it answers, else
    the template."""
    if use_ai:
        from apps.ai.agents import advisor

        written = advisor.write_review(company, review_facts, language=language)
        if written is not None:
            content, model = written
            return content, Briefing.WrittenBy.AI, model
    return writing.template(review_facts, language), Briefing.WrittenBy.TEMPLATE, ""


def store(
    company,
    period: periods.Period,
    reader_scope: scope.Scope,
    language: str,
    review_facts: dict,
    *,
    use_ai: bool,
    rewrite: bool = False,
) -> tuple[Briefing, bool]:
    """The review of `period` for `reader_scope` in `language`: the one already written, or a
    new one (`rewrite` writes the existing one again, with these facts). And whether it was
    written now."""
    where = {
        "company": company,
        "day": period.start,
        "kind": period.kind,
        "language": language,
        "scope_key": reader_scope.key,
    }
    found = Briefing.objects.filter(**where).first()
    if found is not None and not rewrite:
        return found, False
    content, written_by, model = write_content(company, review_facts, language, use_ai=use_ai)
    values = {
        "domains": list(reader_scope.domains),
        "branch_ids": reader_scope.branch_ids,
        "facts": review_facts,
        "content": content,
        "written_by": written_by,
        "model": model,
        "written_at": timezone.now(),
    }
    if found is not None:
        for name, value in values.items():
            setattr(found, name, value)
        found.save()
        return found, True
    try:
        with transaction.atomic():
            return Briefing.objects.create(**where, **values), True
    except IntegrityError:  # written meanwhile by another run
        return Briefing.objects.get(**where), False


def deliver(briefing: Briefing, member: Membership, now: datetime) -> int:
    """Send `briefing` to `member` once: 1 when it went now, 0 when they already had it."""
    from apps.inbox import services as inbox

    with transaction.atomic():
        _delivery, created = BriefingDelivery.objects.get_or_create(
            briefing=briefing,
            membership=member,
            defaults={"via": BriefingDelivery.Via.BOT, "sent_at": now},
        )
        if not created:
            return 0
        kind = NOTIFY_KIND[briefing.kind]
        inbox.notify(
            [member],
            kind,
            title=writing.title(briefing.facts, briefing.language),
            body=writing.bot_text(briefing.content, briefing.language, briefing.kind),
            url=page_url(briefing),
            target=briefing,
            data={"briefing": briefing.pk, "day": briefing.day.isoformat()},
            dedupe_key=f"{kind}:{briefing.pk}:{member.pk}",
        )
    return 1


def send(
    company,
    period: periods.Period,
    now: datetime,
    *,
    use_ai: bool,
    rewrite: bool = False,
    settings: BriefingSettings | None = None,
) -> Outcome:
    """The review of `period` for every reader (one per scope and language), each sent to its
    readers who haven't had it."""
    groups: dict[str, tuple[scope.Scope, dict[str, list[Membership]]]] = {}
    for member in scope.recipients(company, settings):
        found = scope.of(member)
        if not found.has_data:
            continue
        entry = groups.setdefault(found.key, (found, {}))
        entry[1].setdefault(display.lang_of(member.user.language), []).append(member)
    today = local(company, now).date()
    outcome = Outcome()
    for reader_scope, by_language in groups.values():
        review_facts = facts.build(company, period, reader_scope, today=today)
        if facts.is_empty(review_facts):
            continue
        for language, members in sorted(by_language.items()):
            briefing, written = store(
                company,
                period,
                reader_scope,
                language,
                review_facts,
                use_ai=use_ai,
                rewrite=rewrite,
            )
            if written:
                outcome.reviews += 1
                outcome.by_ai += briefing.written_by == Briefing.WrittenBy.AI
            for member in members:
                outcome.sent += deliver(briefing, member, now)
    if outcome.reviews or outcome.sent:
        bump(company.pk, PULSE)
    return outcome


def run_scheduled(company, kind: str, now: datetime, *, use_ai: bool) -> Outcome:
    """The scheduled review of `kind` when it is due (apps.briefings.periods.is_due): written
    and sent, then the period marked sent so it goes once. One run at a time per company."""
    with transaction.atomic():
        row = BriefingSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        moment = local(company, now)
        if not periods.is_due(row, kind, moment):
            return Outcome()
        period = periods.latest(kind, moment.date())
        outcome = send(company, period, now, use_ai=use_ai, settings=row)
        field = f"{kind}_sent_for"
        setattr(row, field, period.start)
        row.save(update_fields=[field, "updated_at"])
    return outcome


def rewrite_latest(company, now: datetime, *, use_ai: bool) -> Outcome:
    """Maslahatchi's "Run now": last week's review written again for every reader now, and
    sent to those who haven't had it."""
    period = periods.latest(Briefing.Kind.WEEKLY, local(company, now).date())
    with transaction.atomic():
        row = BriefingSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        return send(company, period, now, use_ai=use_ai, rewrite=True, settings=row)


def regenerate_for(member: Membership, kind: str, now: datetime, *, use_ai: bool) -> Briefing:
    """`member`'s latest review of `kind` written again now (its facts and its words), for
    their own scope and language. Not sent again: they are looking at it."""
    company = member.company
    today = local(company, now).date()
    period = periods.latest(kind, today)
    reader_scope = scope.of(member)
    review_facts = facts.build(company, period, reader_scope, today=today)
    if facts.is_empty(review_facts):
        raise DomainError(_("There is nothing to review yet: no money moved and nothing was sold."))
    with transaction.atomic():
        briefing, _written = store(
            company,
            period,
            reader_scope,
            display.lang_of(member.user.language),
            review_facts,
            use_ai=use_ai,
            rewrite=True,
        )
        opened(briefing, member, now)
    bump(company.pk, PULSE)
    return briefing


def opened(briefing: Briefing, member: Membership, now: datetime) -> None:
    """The reader opened the review in the dashboard (the first time counts)."""
    delivery, created = BriefingDelivery.objects.get_or_create(
        briefing=briefing,
        membership=member,
        defaults={"via": BriefingDelivery.Via.DASHBOARD, "opened_at": now},
    )
    if not created and delivery.opened_at is None:
        BriefingDelivery.objects.filter(pk=delivery.pk).update(opened_at=now)


# The beat ---------------------------------------------------------------------------------------


def _beat_sends(company, kind: str, moment: datetime, row: BriefingSettings) -> bool:
    """Whether the beat sends this company's review: always where Maslahatchi doesn't write
    them, and where it does only once its run is ADVISOR_GRACE late."""
    if not advisor_writes(company):
        return True
    due = periods.due_moment(row, kind, moment)
    return due is not None and moment - due >= ADVISOR_GRACE


def tick(now: datetime | None = None) -> int:
    """The beat: every company's scheduled reviews that are due; how many people they went to.
    One company's trouble never stops the others."""
    now = now or timezone.now()
    sent = 0
    for company in Company.objects.filter(is_active=True).order_by("pk"):
        if not any(company.has_feature(feature) for feature in DATA_FEATURES):
            continue
        for kind in KINDS:
            try:
                row = conf.get_settings(company)
                moment = local(company, now)
                if periods.is_due(row, kind, moment) and _beat_sends(company, kind, moment, row):
                    sent += run_scheduled(company, kind, now, use_ai=False).sent
            except Exception:
                logger.exception("The %s review of company %s failed", kind, company.pk)
    return sent
