"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`."""

from django.urls import path

from apps.recognition import owner_api

urlpatterns = [
    path(
        "recognition/leaderboard/",
        owner_api.LeaderboardView.as_view(),
        name="recognition-owner-leaderboard",
    ),
    path(
        "recognition/people/<int:member_id>/",
        owner_api.PersonView.as_view(),
        name="recognition-owner-person",
    ),
    path(
        "recognition/people/<int:member_id>/adjust/",
        owner_api.AdjustView.as_view(),
        name="recognition-owner-adjust",
    ),
    path("recognition/kudos/", owner_api.KudosView.as_view(), name="recognition-owner-kudos"),
    path(
        "recognition/kudos/<int:kudos_id>/hide/",
        owner_api.HideKudosView.as_view(),
        name="recognition-owner-kudos-hide",
    ),
    path("recognition/badges/", owner_api.BadgesView.as_view(), name="recognition-owner-badges"),
    path(
        "recognition/settings/",
        owner_api.SettingsView.as_view(),
        name="recognition-owner-settings",
    ),
]
