"""Audit action codes and labels of the company calendar (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AgendaAction(models.TextChoices):
    EVENT_CREATED = "agenda.event_created", _("Added an event to the calendar")
    EVENT_CHANGED = "agenda.event_changed", _("Changed a calendar event")
    EVENT_CANCELLED = "agenda.event_cancelled", _("Cancelled a calendar event")
    ATTENDEES_REMINDED = "agenda.attendees_reminded", _("Reminded the attendees of an event")
    SETTINGS_CHANGED = "agenda.settings_changed", _("Changed the calendar settings")
