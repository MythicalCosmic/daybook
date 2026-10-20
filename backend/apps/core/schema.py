"""OpenAPI schema plumbing: one schema per audience, and enum names from every app.

`split_by_audience` is a drf-spectacular preprocessing hook. `SCHEMA_AUDIENCE=employee` keeps
everything outside `/api/v1/owner/` (the mini app's types come from it), `owner` keeps only
`/api/v1/owner/` (the dashboard's types are checked against it), and unset keeps everything
(`/api/schema/`).

`enum_name_overrides` merges the base names with every `apps/<app>/schema_enums.py`, read by file
path at settings time (see `apps.core.collect`), and raises on a duplicate name.
"""

from apps.core.collect import collect

OWNER_PREFIX = "/api/v1/owner/"
AUDIENCES = ("", "employee", "owner")


def split_by_audience(endpoints, **kwargs):
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    audience = getattr(settings, "SCHEMA_AUDIENCE", "")
    if audience not in AUDIENCES:
        raise ImproperlyConfigured(f"SCHEMA_AUDIENCE must be one of {AUDIENCES}, not {audience!r}.")
    if not audience:
        return endpoints
    owner = audience == "owner"
    return [endpoint for endpoint in endpoints if endpoint[0].startswith(OWNER_PREFIX) == owner]


def enum_name_overrides(base: dict, **kwargs) -> dict:
    return collect("schema_enums.py", "ENUM_NAME_OVERRIDES", base, **kwargs)
