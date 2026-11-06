"""Ready jobs for the agents an owner makes (apps.ai.agents.custom): the "Start from an example"
gallery of the New agent dialog. Each is a job in the owner's words, when it runs, what it reads
and the module it needs; a template whose module is off is not offered, and of its domains only
those whose module is on are kept. Its texts are in the reader's language; once chosen they are
the owner's own words, to change as they like.

    custom_templates.for_company(company)     # [{key, name, job, frequency, at, …}]
"""

from dataclasses import dataclass

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from apps.ai.models import CustomAgent
from apps.ai.tools import registry as tools
from apps.companies.models import Feature

DAILY = CustomAgent.Frequency.DAILY
WEEKDAYS = CustomAgent.Frequency.WEEKDAYS
WEEKLY = CustomAgent.Frequency.WEEKLY
MONTHLY = CustomAgent.Frequency.MONTHLY
MONDAY = 0


@dataclass(frozen=True)
class Template:
    key: str
    name: str | Promise
    job: str | Promise
    frequency: str
    at: str
    domains: tuple[str, ...]
    color: str
    icon: str  # a lucide icon name, for its card in the gallery
    # The module it is about: not offered while that module is off.
    needs: str | None = None
    weekday: int | None = None
    month_day: int | None = None


TEMPLATES = (
    Template(
        key="evening_report",
        name=_("Evening report"),
        job=_(
            "Every workday evening, sum up the day in a few lines: how many tasks were done and "
            "how many are late (name the late ones and whose they are), who came to work late "
            "today, and today's sales at each pharmacy compared with the same weekday last week. "
            "Put anything unusual first."
        ),
        frequency=WEEKDAYS,
        at="20:00",
        domains=("tasks", "reports", "attendance", "sales"),
        color=CustomAgent.Color.INDIGO,
        icon="moon",
    ),
    Template(
        key="monday_best",
        name=_("Monday: the best of last week"),
        job=_(
            "Every Monday morning: who did best last week (tasks done on time, coming to work on "
            "time, and for cashiers their sales) and who needs help, with one or two reasons for "
            "each. Name at most three people in each group."
        ),
        frequency=WEEKLY,
        weekday=MONDAY,
        at="09:00",
        domains=("reports", "tasks", "attendance", "sales"),
        color=CustomAgent.Color.AMBER,
        icon="trophy",
    ),
    Template(
        key="attendance_morning",
        name=_("Who is at work at 10:00"),
        job=_(
            "Every workday at 10:00: who has not come to work yet, who came late today, and which "
            "pharmacy is short of people right now. If everyone is in, say so in one line."
        ),
        frequency=WEEKDAYS,
        at="10:00",
        domains=("attendance", "people"),
        color=CustomAgent.Color.LIME,
        icon="user-check",
        needs=Feature.ATTENDANCE,
    ),
    Template(
        key="week_expenses",
        name=_("Last week's biggest expenses"),
        job=_(
            "Every Monday: last week's biggest expenses by category and the five largest "
            "payments, compared with a usual week (the average of the four weeks before). Say "
            "which expense grew the most, and by how much."
        ),
        frequency=WEEKLY,
        weekday=MONDAY,
        at="09:30",
        domains=("finance",),
        color=CustomAgent.Color.ROSE,
        icon="wallet",
        needs=Feature.FINANCE,
    ),
    Template(
        key="month_summary",
        name=_("The month in short"),
        job=_(
            "On the 1st of each month: last month in short. Sales and profit, the biggest "
            "expenses, how many tasks the team did on time, and what changed most from the month "
            "before. Five to eight lines."
        ),
        frequency=MONTHLY,
        month_day=1,
        at="09:00",
        domains=("sales", "finance", "reports", "people"),
        color=CustomAgent.Color.PLUM,
        icon="calendar-check",
    ),
    Template(
        key="expiring_documents",
        name=_("Documents expiring in 30 days"),
        job=_(
            "Every Monday: the staff documents, certificates and contracts that expire in the "
            "next 30 days or have already expired, whose they are and the date, the most urgent "
            "first. If nothing expires, say so in one line."
        ),
        frequency=WEEKLY,
        weekday=MONDAY,
        at="09:00",
        domains=("hr",),
        color=CustomAgent.Color.SLATE,
        icon="file-clock",
        needs=Feature.HR,
    ),
    Template(
        key="sales_below_usual",
        name=_("A pharmacy sold less than usual"),
        job=_(
            "Every evening, compare today's sales at each pharmacy with its usual for this "
            "weekday (the average of the last four same weekdays). Name every pharmacy that sold "
            "more than 15 percent below its usual, with both numbers. If all are as usual, say so "
            "in one line."
        ),
        frequency=DAILY,
        at="21:00",
        domains=("sales",),
        color=CustomAgent.Color.AQUA,
        icon="trending-down",
        needs=Feature.SALES,
    ),
    Template(
        key="late_work_morning",
        name=_("Late work every morning"),
        job=_(
            "Every workday at 9:00: the tasks that are late, grouped by person with the oldest "
            "first, and who has the most. Say how many there are in all in the first line."
        ),
        frequency=WEEKDAYS,
        at="09:00",
        domains=("tasks",),
        color=CustomAgent.Color.SKY,
        icon="alarm-clock",
    ),
)


def domains_on(company) -> set[str]:
    """The tool domains with at least one tool whose module is on in `company`."""
    return {
        tool.domain
        for tool in tools.all_tools()
        if tool.feature is None or company.has_feature(tool.feature)
    }


def for_company(company) -> list[dict]:
    """The templates `company` may start from, in the active language."""
    on = domains_on(company)
    found = []
    for template in TEMPLATES:
        if template.needs is not None and not company.has_feature(template.needs):
            continue
        domains = [domain for domain in template.domains if domain in on]
        if not domains:
            continue
        found.append(
            {
                "key": template.key,
                "name": str(template.name),
                "job": str(template.job),
                "frequency": template.frequency,
                "at": template.at,
                "weekday": template.weekday,
                "month_day": template.month_day,
                "domains": domains,
                "color": template.color,
                "icon": template.icon,
                "needs": template.needs,
            }
        )
    return found


def get(key: str) -> Template | None:
    return next((template for template in TEMPLATES if template.key == key), None)
