from importlib import import_module

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.accounts.api import MeView, TelegramAuthView
from apps.members.api import MemberListView, OnboardingView, PositionListView
from apps.reminders.api import ReminderPolicyViewSet
from apps.reports.api import TeamStatsView
from apps.tasks.api import (
    ActivityViewSet,
    MyTeamView,
    SummaryView,
    TaskTemplateViewSet,
    TaskViewSet,
    TeamPersonView,
)
from apps.timeoff.api import HolidayListView, TimeOffViewSet

COMPANY = "companies/<int:company_id>"
OWNER_COMPANY = "owner/companies/<int:company_id>/"

# Apps whose urls.py adds employee (mini app) endpoints under companies/<id>/ (§4.1).
EMPLOYEE_APPS = (
    "announcements",
    "timeoff",
    "console",
    "inbox",
    "exports",
    "signin",
    "finance",
    "sales",
    "inventory",
    "attendance",
    "hr",
    "payroll",
    "ai",
    "insights",
    "briefings",
    "recognition",
    "projects",
    "lifecycle",
    "knowledge",
    "agenda",
    "crm",
)

# Apps whose owner_urls.py adds owner endpoints under owner/companies/<id>/ (§4.1). An optional
# `root_urlpatterns` in the same file is mounted at owner/ instead.
OWNER_APPS = (
    "inbox",
    "exports",
    "audit",
    "companies",
    "groups",
    "tasks",
    "reminders",
    "reports",
    "members",
    "timeoff",
    "announcements",
    "finance",
    "sales",
    "inventory",
    "attendance",
    "hr",
    "payroll",
    "ai",
    "insights",
    "briefings",
    "recognition",
    "projects",
    "lifecycle",
    "knowledge",
    "agenda",
    "crm",
)


def private_file(request, token):
    """`/api/v1/files/<token>/`: signed, permission-checked downloads (apps.core.files)."""
    from apps.core.files import PrivateFileView

    return PrivateFileView.as_view()(request, token=token)


router = SimpleRouter()
router.register(r"companies/(?P<company_id>\d+)/tasks", TaskViewSet, basename="task")
router.register(
    r"companies/(?P<company_id>\d+)/task-templates", TaskTemplateViewSet, basename="task-template"
)
router.register(r"companies/(?P<company_id>\d+)/activity", ActivityViewSet, basename="activity")
router.register(r"companies/(?P<company_id>\d+)/time-off", TimeOffViewSet, basename="time-off")
router.register(
    r"companies/(?P<company_id>\d+)/reminder-policies",
    ReminderPolicyViewSet,
    basename="reminder-policy",
)

owner_modules = [import_module(f"apps.{app}.owner_urls") for app in OWNER_APPS]

urlpatterns = [
    # Employee mini app
    path("auth/telegram/", TelegramAuthView.as_view(), name="auth-telegram"),
    path("me/", MeView.as_view(), name="me"),
    path(f"{COMPANY}/members/", MemberListView.as_view(), name="members"),
    path(f"{COMPANY}/positions/", PositionListView.as_view(), name="positions"),
    path(f"{COMPANY}/onboarding/", OnboardingView.as_view(), name="onboarding"),
    path(f"{COMPANY}/summary/", SummaryView.as_view(), name="summary"),
    path(f"{COMPANY}/team-stats/", TeamStatsView.as_view(), name="team-stats"),
    path(f"{COMPANY}/my-team/", MyTeamView.as_view(), name="my-team"),
    path(f"{COMPANY}/my-team/<int:member_id>/", TeamPersonView.as_view(), name="my-team-person"),
    path(f"{COMPANY}/holidays/", HolidayListView.as_view(), name="holidays"),
    *router.urls,
    *(path(f"{COMPANY}/", include(f"apps.{app}.urls")) for app in EMPLOYEE_APPS),
    # Owner dashboard: Bearer tokens with aud="dashboard" only
    path("owner/", include("apps.console.owner_urls")),
    path("owner/auth/", include("apps.signin.owner_urls")),
    path("owner/ai/", include("apps.ai.stream_urls")),
    path(OWNER_COMPANY, include("apps.console.company_urls")),
    *(path(OWNER_COMPANY, include(module)) for module in owner_modules),
    *(
        path("owner/", include(module.root_urlpatterns))
        for module in owner_modules
        if hasattr(module, "root_urlpatterns")
    ),
    # Private files
    path("files/<str:token>/", private_file, name="private-file"),
]
