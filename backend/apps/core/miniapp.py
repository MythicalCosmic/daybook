"""Serves the built mini app at /app/ next to the API, so the two share an origin."""

import re

from django.conf import settings as django_settings
from whitenoise.middleware import WhiteNoiseMiddleware

# Vite fingerprints everything it emits under assets/, e.g. assets/index-BJyE8SXe.js.
VITE_ASSET = re.compile(r"^/app/assets/.+-[A-Za-z0-9_-]{8}\.\w+$")


class MiniAppWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    def __init__(self, get_response=None, settings=django_settings):
        super().__init__(get_response, settings)
        if settings.MINIAPP_DIST.is_dir():
            self.add_files(str(settings.MINIAPP_DIST), prefix="app/")

    def immutable_file_test(self, path, url):
        return bool(VITE_ASSET.match(url)) or super().immutable_file_test(path, url)
