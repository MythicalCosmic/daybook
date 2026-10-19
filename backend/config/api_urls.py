from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.api import MeView, TelegramAuthView
from apps.members.api import MemberListView, OnboardingView, PositionListView
from apps.tasks.api import TaskTemplateViewSet, TaskViewSet

COMPANY = "companies/<int:company_id>"

router = SimpleRouter()
router.register(r"companies/(?P<company_id>\d+)/tasks", TaskViewSet, basename="task")
router.register(
    r"companies/(?P<company_id>\d+)/task-templates", TaskTemplateViewSet, basename="task-template"
)

urlpatterns = [
    path("auth/telegram/", TelegramAuthView.as_view(), name="auth-telegram"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("me/", MeView.as_view(), name="me"),
    path(f"{COMPANY}/members/", MemberListView.as_view(), name="members"),
    path(f"{COMPANY}/positions/", PositionListView.as_view(), name="positions"),
    path(f"{COMPANY}/onboarding/", OnboardingView.as_view(), name="onboarding"),
    *router.urls,
]
