"""The base `AppConfig` of every project app: `ready()` imports `<app>.hooks` when it exists.

`hooks.py` is where an app registers itself with the shared registries and connects its signal
receivers, so adding one never means editing `apps.py` or any shared file.

Import the module, not the class (`from apps.core import appconfig`, then
`class SalesConfig(appconfig.AppConfig)`): Django uses the only AppConfig subclass it finds in
`apps.py`, and an imported base class would make two.
"""

import importlib
import importlib.util

from django.apps import AppConfig as DjangoAppConfig


def import_hooks(app_name: str) -> bool:
    """Import `<app_name>.hooks` if the app has one. Errors inside it are not swallowed."""
    name = f"{app_name}.hooks"
    if importlib.util.find_spec(name) is None:
        return False
    importlib.import_module(name)
    return True


class AppConfig(DjangoAppConfig):
    def ready(self):
        import_hooks(self.name)
