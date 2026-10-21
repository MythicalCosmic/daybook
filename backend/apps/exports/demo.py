"""Demo data of exports: three files the owner downloaded this week (last week's overdue tasks,
last month's timesheet and the profit and loss), built through the real exporters once every
other demo has written its rows."""

from datetime import timedelta

from apps.core import demo_plan
from apps.core.demo_time import moment
from apps.exports import build, services
from apps.exports.models import Export
from apps.exports.registry import get_exporter


def seed(company, people, now) -> None:
    """Nothing to do before the other demos: the files are built in `finish`."""


def finish(company, people, now) -> None:
    """Request and build the owner's exports, as if done over the last few days."""
    story = demo_plan.Plan(company, people, now)
    owner = people["owner"]
    last_month = (story.today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    wanted = [
        (
            "tasks.list",
            "xlsx",
            {"due_from": str(story.day(-7)), "due_to": str(story.day(-1)), "overdue": "true"},
            3,
        ),
        ("attendance.timesheet", "xlsx", {"month": last_month}, 2),
        ("finance.pnl", "xlsx", {}, 1),
    ]
    for kind, format_, params, days_ago in wanted:
        exporter = get_exporter(kind)
        if exporter is None or (exporter.feature and not company.has_feature(exporter.feature)):
            continue
        at = now - timedelta(days=days_ago, hours=2)
        with moment(at):
            export = services.request_export(owner, kind, format=format_, params=params)
        with moment(at + timedelta(seconds=20)):
            build.build(export.pk)
        Export.objects.filter(pk=export.pk).update(created_at=at)
