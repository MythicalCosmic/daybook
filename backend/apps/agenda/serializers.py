"""Shapes of the company calendar API (owner dashboard and mini app)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.agenda import queries
from apps.agenda.models import Event, EventAttendee
from apps.members.models import Membership


def person(member: Membership | None) -> dict | None:
    if member is None:
        return None
    user = getattr(member, "user", None)
    photo = getattr(user, "photo", None) if user is not None else None
    return {
        "id": member.pk,
        "name": member.full_name or (str(user) if user else f"#{member.pk}"),
        "photo_url": photo.url if photo else None,
    }


class AgendaPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class AgendaCalendarItemSerializer(serializers.Serializer):
    """One date on the calendar. `id` is unique across sources ("agenda.events:12-20261027");
    all-day items carry days (`end` inclusive), timed ones ISO instants. `color` is a design
    token name ("chart-3", "success") the client turns into a colour."""

    id = serializers.CharField()
    source = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    start = serializers.CharField()
    end = serializers.CharField(allow_null=True)
    all_day = serializers.BooleanField()
    color = serializers.CharField()
    url = serializers.CharField()
    subtitle = serializers.CharField(help_text="Where a company event happens; empty otherwise.")


class AgendaSourceSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class AgendaAttendeeSerializer(serializers.ModelSerializer):
    member = serializers.SerializerMethodField()

    class Meta:
        model = EventAttendee
        fields = ["member", "response", "responded_at"]

    @extend_schema_field(serializers.DictField(help_text="{id, name, photo_url, position}"))
    def get_member(self, invite) -> dict:
        member = invite.membership
        return person(member) | {"position": member.position.name if member.position else None}


def _iso(event: Event, moment: datetime | None, *, end: bool = False) -> str | None:
    if moment is None:
        return None
    if event.all_day:
        return queries.local_day(moment, event.company).isoformat()
    return timezone.localtime(moment, queries.tz_of(event.company)).isoformat()


class AgendaEventSerializer(serializers.ModelSerializer):
    start = serializers.SerializerMethodField()
    end = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    attendees = serializers.SerializerMethodField()
    responses = serializers.SerializerMethodField()
    my_response = serializers.SerializerMethodField()
    cancelled = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "description",
            "kind",
            "color",
            "start",
            "end",
            "all_day",
            "place",
            "branch",
            "visibility",
            "remind_before",
            "repeat",
            "repeat_until",
            "created_by",
            "attendees",
            "responses",
            "my_response",
            "cancelled",
            "cancel_reason",
            "can_edit",
            "created_at",
            "updated_at",
        ]

    def get_start(self, event) -> str:
        return _iso(event, event.start)

    def get_end(self, event) -> str | None:
        return _iso(event, event.end, end=True)

    @extend_schema_field(serializers.DictField(allow_null=True, help_text="{id, name}"))
    def get_branch(self, event) -> dict | None:
        return {"id": event.branch.pk, "name": event.branch.name} if event.branch else None

    @extend_schema_field(AgendaPersonSerializer(allow_null=True))
    def get_created_by(self, event) -> dict | None:
        return person(event.created_by)

    @extend_schema_field(AgendaAttendeeSerializer(many=True))
    def get_attendees(self, event) -> list[dict]:
        if self.context.get("compact"):
            return []
        invites = event.invites.select_related("membership__user", "membership__position").order_by(
            "membership__first_name", "membership__last_name"
        )
        return AgendaAttendeeSerializer(invites, many=True).data

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_responses(self, event) -> dict:
        return queries.responses(event)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_my_response(self, event) -> str | None:
        if hasattr(event, "my_answer"):
            return event.my_answer
        member = self.context.get("membership")
        invite = queries.my_invite(member, event) if member else None
        return invite.response if invite else None

    def get_cancelled(self, event) -> bool:
        return event.cancelled_at is not None

    def get_can_edit(self, event) -> bool:
        member = self.context.get("membership")
        return (
            bool(member and not self.context.get("reader") and queries.can_manage(member))
            and event.cancelled_at is None
        )

    def get_color(self, event) -> str:
        return queries.KIND_COLORS.get(event.kind, "chart-3")


@extend_schema_field(OpenApiTypes.STR)
class FlexibleMoment(serializers.Field):
    """A day ("2026-10-24") or a moment ("2026-10-24T10:00", company time when naive)."""

    def to_internal_value(self, data):
        if not isinstance(data, str) or not data:
            raise serializers.ValidationError(_("Give a date or a date and time."))
        if len(data) == 10:
            try:
                day = parse_date(data)
            except ValueError:
                day = None
            if day is None:
                raise serializers.ValidationError(_("Use a date like 2026-10-24."))
            return day
        try:
            moment = parse_datetime(data)
        except ValueError:
            moment = None
        if moment is None:
            raise serializers.ValidationError(_("Use a time like 2026-10-24T10:00."))
        return moment

    def to_representation(self, value):
        return value.isoformat()


class AgendaEventWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
    )
    kind = serializers.ChoiceField(choices=Event.Kind.choices, default=Event.Kind.MEETING)
    start = FlexibleMoment()
    end = FlexibleMoment(required=False, allow_null=True, default=None)
    all_day = serializers.BooleanField(required=False, default=False)
    place = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    branch = serializers.IntegerField(required=False, allow_null=True, default=None)
    visibility = serializers.ChoiceField(
        choices=Event.Visibility.choices, default=Event.Visibility.COMPANY
    )
    attendee_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list, max_length=300
    )
    remind_before = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=10080
    )
    repeat = serializers.ChoiceField(choices=Event.Repeat.choices, default=Event.Repeat.NONE)
    repeat_until = serializers.DateField(required=False, allow_null=True, default=None)


class AgendaEventUpdateSerializer(AgendaEventWriteSerializer):
    """Every field optional: only what is sent changes."""

    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            field.required = False
            if hasattr(field, "default"):
                field.default = serializers.empty
        return fields


class AgendaCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=300)


class AgendaRespondSerializer(serializers.Serializer):
    response = serializers.ChoiceField(
        choices=[EventAttendee.Response.GOING, EventAttendee.Response.DECLINED]
    )


class AgendaPeopleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    subtitle = serializers.CharField()
    position_id = serializers.IntegerField(allow_null=True)
    branch_ids = serializers.ListField(child=serializers.IntegerField())


class AgendaSettingsSerializer(serializers.Serializer):
    default_remind_before = serializers.IntegerField(allow_null=True, min_value=0, max_value=10080)
    notify_invites = serializers.BooleanField()


def _day(params, name: str) -> date | None:
    text = params.get(name)
    if not text:
        return None
    try:
        day = parse_date(text)
    except ValueError:
        day = None
    if day is None:
        raise serializers.ValidationError({name: [_("Use a date like 2026-10-24.")]})
    return day


def window(params, company) -> tuple[date, date]:
    """The calendar window from `from`/`to` (company days, inclusive); 62 days at most."""
    first = _day(params, "from") or queries.local_day(timezone.now(), company)
    last = _day(params, "to") or first + timedelta(days=30)
    if last < first:
        raise serializers.ValidationError({"to": [_("The end can't be before the start.")]})
    if (last - first).days > 62:
        raise serializers.ValidationError({"to": [_("Ask for at most two months at a time.")]})
    return first, last


def item_json(source: str, item, company) -> dict:
    """A registry `CalendarItem` as the API sends it."""
    zone = queries.tz_of(company)

    def moment(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            if item.all_day:
                return (
                    timezone.localtime(value, zone).date().isoformat()
                    if timezone.is_aware(value)
                    else value.date().isoformat()
                )
            return (
                timezone.localtime(value, zone).isoformat()
                if timezone.is_aware(value)
                else value.replace(tzinfo=zone).isoformat()
            )
        if isinstance(value, date):
            if item.all_day:
                return value.isoformat()
            return datetime.combine(value, time(0), tzinfo=zone).isoformat()
        return str(value)

    return {
        "id": f"{source}:{item.id}",
        "source": source,
        "kind": item.kind,
        "title": str(item.title),
        "start": moment(item.start),
        "end": moment(item.end),
        "all_day": bool(item.all_day),
        "color": item.color or "",
        "url": item.url or "",
    }
