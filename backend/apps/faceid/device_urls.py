"""Where devices post, mounted at `/api/v1/devices/`: `hik/<code>/` (the trailing slash may be
left out, some firmware drops it)."""

from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt

from apps.faceid.device_api import HikvisionView

urlpatterns = [
    re_path(
        r"^hik/(?P<token>[A-Za-z0-9_-]{16,64})/?$",
        csrf_exempt(HikvisionView.as_view()),
        name="faceid-device",
    ),
]
