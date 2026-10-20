"""Registrations of team reports with the shared registries (docs/PLAN-OWNER.md §11.3, Package
B). Imported by `AppConfig.ready()`."""

from django.utils.translation import gettext_lazy as _

from apps.exports.registry import Column, register_exporter
from apps.members.permissions import Perm
from apps.reports import exporters

register_exporter(
    "reports.team",
    perm=Perm.REPORTS_VIEW,
    label=_("Team results"),
    columns=[
        Column("label", _("Name")),
        Column("position", _("Position")),
        Column("total", _("Due"), "number"),
        Column("on_time", _("On time"), "number"),
        Column("late", _("Late"), "number"),
        Column("missed", _("Missed"), "number"),
        Column("on_time_percent", _("On time, %"), "number"),
        Column("avg_delay_minutes", _("Average delay, min"), "number"),
        Column("late_now", _("Late now"), "number"),
        Column("reminders", _("Reminders"), "number"),
    ],
    rows=exporters.team_rows,
)
