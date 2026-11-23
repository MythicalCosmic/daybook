"""Where the Ko‘z boxes call, mounted at `/api/v1/devices/koz/` (docs/KOZ.md §5)."""

from django.urls import path, re_path

from apps.vision import device_api

KEY = r"(?P<key>[a-z0-9:_-]{1,64})"

urlpatterns = [
    path("pair/", device_api.PairView.as_view(), name="vision-device-pair"),
    path("config/", device_api.ConfigView.as_view(), name="vision-device-config"),
    path("cameras/", device_api.CamerasView.as_view(), name="vision-device-cameras"),
    re_path(
        rf"^cameras/{KEY}/snapshot/$",
        device_api.SnapshotView.as_view(),
        name="vision-device-snapshot",
    ),
    path("live/", device_api.LiveView.as_view(), name="vision-device-live"),
    re_path(rf"^frames/{KEY}/$", device_api.FrameView.as_view(), name="vision-device-frame"),
    path("stats/", device_api.StatsView.as_view(), name="vision-device-stats"),
    path("events/", device_api.EventsView.as_view(), name="vision-device-events"),
    path("jobs/", device_api.JobsView.as_view(), name="vision-device-jobs"),
    path("clips/<int:clip_id>/", device_api.ClipView.as_view(), name="vision-device-clip"),
]
