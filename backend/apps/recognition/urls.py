"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.recognition import api

urlpatterns = [
    path("recognition/me/", api.MeView.as_view(), name="recognition-me"),
    path("recognition/seen/", api.SeenView.as_view(), name="recognition-seen"),
    path("recognition/leaderboard/", api.LeaderboardView.as_view(), name="recognition-leaderboard"),
    path("recognition/kudos/", api.KudosView.as_view(), name="recognition-kudos"),
    path(
        "recognition/kudos/colleagues/",
        api.ColleaguesView.as_view(),
        name="recognition-kudos-colleagues",
    ),
]
