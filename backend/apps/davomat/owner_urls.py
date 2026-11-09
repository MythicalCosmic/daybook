"""Davomat's owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/` (404 in
the Daybook edition). `root_urlpatterns` is mounted at `/api/v1/owner/`: the edition, the
first-run setup and password sign-in happen outside any company."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.davomat import owner_api

router = SimpleRouter()
router.register("users", owner_api.UserViewSet, basename="davomat-user")
router.register("employees", owner_api.EmployeeViewSet, basename="davomat-employee")

urlpatterns = [
    path("davomat/settings/", owner_api.SettingsView.as_view(), name="davomat-settings"),
    path("telegram/", owner_api.TelegramView.as_view(), name="davomat-telegram"),
    path("telegram/test/", owner_api.TelegramTestView.as_view(), name="davomat-telegram-test"),
    *router.urls,
]

root_urlpatterns = [
    path("edition/", owner_api.EditionView.as_view(), name="davomat-edition"),
    path("edition/setup/", owner_api.SetupView.as_view(), name="davomat-setup"),
    path("auth/password/", owner_api.PasswordLoginView.as_view(), name="davomat-password-login"),
    path(
        "auth/password/change/",
        owner_api.PasswordChangeView.as_view(),
        name="davomat-password-change",
    ),
]
