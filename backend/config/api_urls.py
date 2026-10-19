from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.api import MeView, TelegramAuthView
from apps.members.api import OnboardingView, PositionListView

urlpatterns = [
    path("auth/telegram/", TelegramAuthView.as_view(), name="auth-telegram"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("companies/<int:company_id>/positions/", PositionListView.as_view(), name="positions"),
    path("companies/<int:company_id>/onboarding/", OnboardingView.as_view(), name="onboarding"),
]
