"""Business logic of the company calendar: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

Events are created and changed by holders of `agenda.manage`; invited people answer for
themselves. Invitations, changes of time or place, cancellations and reminders reach the
attendees through the inbox (Telegram copies through the employee bot).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.agenda import bot_messages, queries
from apps.agenda.audit_actions import AgendaAction
from apps.agenda.conf import get_settings
from apps.agenda.models import AgendaSettings, Event, EventAttendee
from apps.audit import services as audit
from apps.companies.models import Branch
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.inbox.services import NotificationAction, notify
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

PULSE_KEY = "agenda.events"
KIND_INVITE = "agenda.event_invite"
KIND_CHANGED = "agenda.event_changed"
KIND_REMINDER = "agenda.event_reminder"
MAX_REMIND_MINUTES = 7 * 24 * 60
MAX_ATTENDEES = 300
EDITABLE = (
    "title",
    "description",
    "kind",
    "start",
    "end",
    "all_day",
    "place",
    "branch",
    "visibility",
    "attendee_ids",
    "remind_before",
    "repeat",
    "repeat_until",
)


def ensure_manager(by: Membership | None) -> None:
    if by is not None and not by.has_perm(Perm.AGENDA_MANAGE):
        raise PermissionDenied(_("Only people who manage the calendar can do this."))


def _audit(action: str, event: Event, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=event.company_id,
        actor=by.user if by is not None else None,
        target=event,
        **details,
    )


def _bump(company_id: int) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))


def _rsvp_actions() -> list[NotificationAction]:
    return [
        NotificationAction("going", lambda person: bot_messages.going_button(), "primary"),
        NotificationAction("decline", lambda person: bot_messages.decline_button(), "default"),
    ]


# Validation -----------------------------------------------------------------------------


def _clean_times(
    company, *, start: datetime | date, end: datetime | date | None, all_day: bool
) -> tuple[datetime, datetime | None]:
    """Instants to store. All-day events take days (or moments, whose local days count)."""
    if all_day:
        first = start if not isinstance(start, datetime) else queries.local_day(start, company)
        last = (
            end if end is None or not isinstance(end, datetime) else queries.local_day(end, company)
        )
        if last is not None and last < first:
            raise DomainError(_("The event can't end before it starts."))
        start_at = queries.local_midnight(first, company)
        end_at = queries.local_midnight(last, company) if last and last != first else None
        return start_at, end_at
    if not isinstance(start, datetime):
        raise DomainError(_("Give the time it starts, or make it an all-day event."))
    if timezone.is_naive(start):
        start = timezone.make_aware(start, queries.tz_of(company))
    if end is not None:
        if not isinstance(end, datetime):
            raise DomainError(_("Give the time it ends."))
        if timezone.is_naive(end):
            end = timezone.make_aware(end, queries.tz_of(company))
        if end <= start:
            raise DomainError(_("The event must end after it starts."))
        if end - start > timedelta(days=14):
            raise DomainError(_("A timed event can last two weeks at most. Make it all-day."))
    return start, end


def _clean_repeat(repeat: str, repeat_until: date | None, start: datetime, company) -> date | None:
    if repeat not in Event.Repeat.values:
        raise DomainError(_("Pick how it repeats."))
    if repeat == Event.Repeat.NONE:
        return None
    if repeat_until is not None and repeat_until < queries.local_day(start, company):
        raise DomainError(_("It can't stop repeating before it starts."))
    return repeat_until


def _clean_remind(minutes) -> int | None:
    if minutes in (None, ""):
        return None
    minutes = int(minutes)
    if minutes < 0 or minutes > MAX_REMIND_MINUTES:
        raise DomainError(_("A reminder can come at most a week before."))
    return minutes


def _branch(company, by: Membership | None, branch) -> Branch | None:
    if branch in (None, ""):
        return None
    branch_id = branch.pk if isinstance(branch, Branch) else int(branch)
    row = Branch.objects.filter(company=company, pk=branch_id).first()
    if row is None:
        raise DomainError(_("Pick a branch of this company."))
    if by is not None and not scope.allows(scope.branch_ids(by), row.pk):
        raise DomainError(_("You can only add events at your own branches."))
    return row


def _people(company, by: Membership | None, ids) -> list[Membership]:
    ids = {int(pk) for pk in ids or ()}
    if len(ids) > MAX_ATTENDEES:
        raise DomainError(_("Invite at most %(n)d people.") % {"n": MAX_ATTENDEES})
    rows = Membership.objects.filter(
        company=company, pk__in=ids, status=Membership.Status.APPROVED
    ).select_related("user")
    if by is not None:
        rows = scope.restrict(rows, scope.branch_ids(by), field="branches")
    found = list(rows)
    if len(found) != len(ids):
        raise DomainError(_("Invite people of this company you can see."))
    return found


# Writes ---------------------------------------------------------------------------------


@transaction.atomic
def create_event(
    company,
    *,
    by: Membership | None,
    title: str,
    start: datetime | date,
    end: datetime | date | None = None,
    all_day: bool = False,
    description: str = "",
    kind: str = Event.Kind.MEETING,
    place: str = "",
    branch=None,
    visibility: str = Event.Visibility.COMPANY,
    attendee_ids=(),
    remind_before: int | str | None = "default",
    repeat: str = Event.Repeat.NONE,
    repeat_until: date | None = None,
) -> Event:
    ensure_manager(by)
    title = " ".join((title or "").split())
    if not title:
        raise DomainError(_("Give the event a name."))
    if kind not in Event.Kind.values:
        raise DomainError(_("Pick a kind of event."))
    if visibility not in Event.Visibility.values:
        raise DomainError(_("Pick who sees the event."))
    start_at, end_at = _clean_times(company, start=start, end=end, all_day=all_day)
    if remind_before == "default":
        remind_before = get_settings(company).default_remind_before
    people = _people(company, by, attendee_ids)
    event = Event.objects.create(
        company=company,
        title=title[:200],
        description=(description or "").strip()[:5000],
        kind=kind,
        start=start_at,
        end=end_at,
        all_day=all_day,
        place=(place or "").strip()[:200],
        branch=_branch(company, by, branch),
        visibility=visibility,
        remind_before=_clean_remind(remind_before),
        repeat=repeat,
        repeat_until=_clean_repeat(repeat, repeat_until, start_at, company),
        created_by=by,
    )
    _invite(event, people, by)
    _audit(AgendaAction.EVENT_CREATED, event, by, title=event.title, attendees=len(people))
    _bump(company.pk)
    return event


def _invite(event: Event, people: list[Membership], by: Membership | None) -> list[Membership]:
    existing = set(event.invites.values_list("membership_id", flat=True))
    new = [person for person in people if person.pk not in existing]
    EventAttendee.objects.bulk_create(
        [
            EventAttendee(
                company_id=event.company_id,
                event=event,
                membership=person,
                # The organiser is going to their own meeting.
                response=EventAttendee.Response.GOING
                if by is not None and person.pk == by.pk
                else EventAttendee.Response.PENDING,
                responded_at=timezone.now() if by is not None and person.pk == by.pk else None,
            )
            for person in new
        ]
    )
    recipients = [person for person in new if by is None or person.pk != by.pk]
    if recipients and get_settings(event.company).notify_invites:
        notify(
            recipients,
            KIND_INVITE,
            title=lambda person: bot_messages.invite_title(event),
            body=lambda person: bot_messages.event_line(event),
            app_screen=bot_messages.app_screen(event),
            url=bot_messages.dashboard_url(event),
            target=event,
            actor=by,
            actions=_rsvp_actions(),
        )
    return new


@transaction.atomic
def update_event(event: Event, *, by: Membership | None, **changes) -> Event:
    """Change an event. Attendees hear when its time or place changes; new attendees are
    invited; people taken off the list stop getting reminders."""
    ensure_manager(by)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} on an event.")
    event = Event.objects.select_for_update().select_related("company").get(pk=event.pk)
    if event.cancelled_at is not None:
        raise DomainError(_("This event was cancelled."))
    company = event.company
    if by is not None and not queries.visible_events(by).filter(pk=event.pk).exists():
        raise PermissionDenied(_("You don't have access to this event."))
    before = (event.start, event.end, event.all_day, event.place, event.repeat)
    if "title" in changes:
        title = " ".join((changes["title"] or "").split())
        if not title:
            raise DomainError(_("Give the event a name."))
        event.title = title[:200]
    if "description" in changes:
        event.description = (changes["description"] or "").strip()[:5000]
    if "kind" in changes:
        if changes["kind"] not in Event.Kind.values:
            raise DomainError(_("Pick a kind of event."))
        event.kind = changes["kind"]
    if "place" in changes:
        event.place = (changes["place"] or "").strip()[:200]
    if "visibility" in changes:
        if changes["visibility"] not in Event.Visibility.values:
            raise DomainError(_("Pick who sees the event."))
        event.visibility = changes["visibility"]
    if "branch" in changes:
        event.branch = _branch(company, by, changes["branch"])
    if "remind_before" in changes:
        event.remind_before = _clean_remind(changes["remind_before"])
    if {"start", "end", "all_day"} & set(changes):
        all_day = changes.get("all_day", event.all_day)
        start = changes.get("start", event.start)
        end = changes.get("end", event.end)
        if all_day and not event.all_day:
            # Turning a timed event all-day: its days, not its times.
            start = start if not isinstance(start, datetime) else queries.local_day(start, company)
            end = end if not isinstance(end, datetime) else queries.local_day(end, company)
        event.start, event.end = _clean_times(company, start=start, end=end, all_day=all_day)
        event.all_day = all_day
    if "repeat" in changes or "repeat_until" in changes:
        event.repeat = changes.get("repeat", event.repeat)
        event.repeat_until = _clean_repeat(
            event.repeat, changes.get("repeat_until", event.repeat_until), event.start, company
        )
    event.save()
    moved = before != (event.start, event.end, event.all_day, event.place, event.repeat)
    if moved:
        # A new time is a new reminder.
        event.invites.update(reminded_for=None)
    added: list[Membership] = []
    removed = 0
    if "attendee_ids" in changes:
        people = _people(company, by, changes["attendee_ids"])
        keep = {person.pk for person in people}
        removed, _deleted = event.invites.exclude(membership_id__in=keep).delete()
        added = _invite(event, people, by)
    if moved:
        stayed = [
            invite.membership
            for invite in event.invites.select_related("membership__user").exclude(
                response=EventAttendee.Response.DECLINED
            )
            if invite.membership not in added and (by is None or invite.membership_id != by.pk)
        ]
        if stayed:
            notify(
                stayed,
                KIND_CHANGED,
                title=lambda person: bot_messages.changed_title(event),
                body=lambda person: bot_messages.event_line(event),
                app_screen=bot_messages.app_screen(event),
                url=bot_messages.dashboard_url(event),
                target=event,
                actor=by,
            )
    _audit(
        AgendaAction.EVENT_CHANGED,
        event,
        by,
        changed=sorted(changes),
        invited=len(added),
        uninvited=removed,
    )
    _bump(company.pk)
    return event


@transaction.atomic
def cancel_event(event: Event, *, by: Membership | None, reason: str = "") -> Event:
    ensure_manager(by)
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.cancelled_at is not None:
        return event
    if by is not None and not queries.visible_events(by).filter(pk=event.pk).exists():
        raise PermissionDenied(_("You don't have access to this event."))
    event.cancelled_at = timezone.now()
    event.cancel_reason = (reason or "").strip()[:300]
    event.save(update_fields=["cancelled_at", "cancel_reason", "updated_at"])
    people = [
        invite.membership
        for invite in event.invites.select_related("membership__user").exclude(
            response=EventAttendee.Response.DECLINED
        )
        if by is None or invite.membership_id != by.pk
    ]
    if people:
        notify(
            people,
            KIND_CHANGED,
            title=lambda person: bot_messages.cancelled_title(event),
            body=lambda person: bot_messages.cancelled_body(event),
            app_screen=bot_messages.app_screen(event),
            url=bot_messages.dashboard_url(event),
            target=event,
            actor=by,
            severity="warning",
        )
    _audit(AgendaAction.EVENT_CANCELLED, event, by, reason=event.cancel_reason)
    _bump(event.company_id)
    return event


def respond(event: Event, *, by: Membership, response: str) -> EventAttendee:
    """An attendee says whether they're coming."""
    if response not in (EventAttendee.Response.GOING, EventAttendee.Response.DECLINED):
        raise DomainError(_("Answer going or can't come."))
    with transaction.atomic():
        invite = (
            EventAttendee.objects.select_for_update()
            .select_related("event")
            .filter(event_id=event.pk, membership=by)
            .first()
        )
        if invite is None:
            raise PermissionDenied(_("You're not invited to this event."))
        if invite.event.cancelled_at is not None:
            raise DomainError(_("This event was cancelled."))
        if invite.response != response:
            invite.response = response
            invite.responded_at = timezone.now()
            invite.save(update_fields=["response", "responded_at", "updated_at"])
            _bump(event.company_id)
    return invite


def remind_now(event: Event, *, by: Membership | None) -> int:
    """Send the attendees a reminder of the next occurrence now; returns how many."""
    ensure_manager(by)
    event = Event.objects.select_related("company").get(pk=event.pk)
    if event.cancelled_at is not None:
        raise DomainError(_("This event was cancelled."))
    now = timezone.now()
    today = queries.local_day(now, event.company)
    upcoming = [
        occurrence
        for occurrence in queries.occurrences(event, today, today + timedelta(days=400))
        if (occurrence.end or occurrence.start) >= now
    ]
    if not upcoming:
        raise DomainError(_("This event is over."))
    people = [
        invite.membership
        for invite in event.invites.select_related("membership__user").exclude(
            response=EventAttendee.Response.DECLINED
        )
        if by is None or invite.membership_id != by.pk
    ]
    if people:
        _send_reminder(upcoming[0], people, by)
        if by is not None:
            _audit(AgendaAction.ATTENDEES_REMINDED, event, by, people=len(people))
    return len(people)


def _send_reminder(occurrence, people: list[Membership], by: Membership | None) -> None:
    event = occurrence.event
    notify(
        people,
        KIND_REMINDER,
        title=lambda person: bot_messages.reminder_title(occurrence),
        body=lambda person: bot_messages.occurrence_line(occurrence),
        app_screen=bot_messages.app_screen(event),
        url=bot_messages.dashboard_url(event),
        target=event,
        actor=by,
        dedupe_key=f"agenda:{occurrence.key}:{int(occurrence.start.timestamp())}"
        if by is None
        else "",
    )


def send_due_reminders(now: datetime | None = None) -> int:
    """Celery, every minute: remind attendees of occurrences whose reminder time has come and
    that haven't started. Each attendee gets one reminder per occurrence. Returns how many."""
    now = now or timezone.now()
    sent = 0
    candidates = (
        Event.objects.filter(cancelled_at__isnull=True, remind_before__isnull=False)
        .filter(company__is_active=True)
        # Single events starting within the longest reminder; repeating ones still running.
        .filter(_due_window(now))
        .select_related("company")
    )
    for event in candidates:
        first = queries.local_day(now, event.company) - timedelta(days=1)
        last = first + timedelta(days=9)
        for occurrence in queries.occurrences(event, first, last):
            due = queries.reminder_time(occurrence)
            if due is None or not (due <= now < occurrence.start + _grace(event)):
                continue
            sent += _remind_occurrence(occurrence)
    return sent


def _grace(event: Event) -> timedelta:
    # All-day reminders run at 09:00 of the day itself when asked for "at the start".
    return timedelta(hours=12) if event.all_day else timedelta(0)


def _due_window(now: datetime) -> Q:
    """Events that may have an occurrence to remind about around `now`."""
    horizon = now + timedelta(minutes=MAX_REMIND_MINUTES + 24 * 60)
    single = Q(repeat=Event.Repeat.NONE, start__gte=now - timedelta(days=1), start__lte=horizon)
    repeating = ~Q(repeat=Event.Repeat.NONE) & (
        Q(repeat_until__isnull=True) | Q(repeat_until__gte=(now - timedelta(days=1)).date())
    )
    return single | repeating


def _remind_occurrence(occurrence) -> int:
    event = occurrence.event
    with transaction.atomic():
        invites = list(
            EventAttendee.objects.select_for_update(skip_locked=True)
            .select_related("membership__user")
            .filter(event=event)
            .exclude(response=EventAttendee.Response.DECLINED)
            .exclude(reminded_for=occurrence.start)
        )
        if not invites:
            return 0
        EventAttendee.objects.filter(pk__in=[invite.pk for invite in invites]).update(
            reminded_for=occurrence.start
        )
        with translation.override(event.company.default_language):
            _send_reminder(occurrence, [invite.membership for invite in invites], None)
    return len(invites)


@transaction.atomic
def update_settings(company, *, by: Membership | None, **changes) -> AgendaSettings:
    ensure_manager(by)
    row = get_settings(company)
    unknown = set(changes) - {"default_remind_before", "notify_invites"}
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} in the calendar settings.")
    if "default_remind_before" in changes:
        changes["default_remind_before"] = _clean_remind(changes["default_remind_before"])
    for name, value in changes.items():
        setattr(row, name, value)
    row.save()
    if by is not None:
        audit.record(
            AgendaAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=row,
            changed=sorted(changes),
        )
    _bump(company.pk)
    return row
