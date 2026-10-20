"""Signed, permission-checked downloads of private files (docs/PLAN-OWNER.md §2.8).

Private files (`apps.core.storage.private_storage`) have no URL of their own. An endpoint that
shows one hands out a short-lived signed link instead:

    url = files.signed_url(doc.file, user=request.user, company_id=doc.company_id,
                           check=f"hr.document:{doc.pk}")      # /api/v1/files/<token>/

The token names the file, the user it was made for, the company and a check. When the link
is opened, `PrivateFileView` verifies the signature and the expiry, that the user is still an
approved member of the company, and then asks the check registered for the kind (here
`hr.document`) whether that user may still open object 12, so a link stops working as soon as
the person loses access. A browser can't send a Bearer header from an `<img>` or a download
link, so the token itself is the credential; that is why it is bound to one user, one object
and a few minutes.

Modules register their checks in `hooks.py`:

    register_file_check("hr.document", lambda user, company_id, object_id: ...)

Files are served only with the types this module knows, never sniffed, sandboxed, and inline
only for pictures and PDFs; everything else is a download.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from django.apps import apps as django_apps
from django.core import signing
from django.core.files.storage import Storage, default_storage
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.storage import SANDBOX_HEADERS, private_storage

logger = logging.getLogger(__name__)

FileCheck = Callable[[object, int, int], bool]

SALT = "apps.core.files"
DEFAULT_TTL = 600
MAX_TTL = 7 * 24 * 60 * 60

# Extension -> (content type, opened in the browser). Anything else is never served.
SERVED_TYPES = {
    ".jpg": ("image/jpeg", True),
    ".jpeg": ("image/jpeg", True),
    ".png": ("image/png", True),
    ".webp": ("image/webp", True),
    ".pdf": ("application/pdf", True),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False),
    ".csv": ("text/csv; charset=utf-8", False),
    ".zip": ("application/zip", False),
}

STORAGES: dict[str, Storage] = {"private": private_storage, "default": default_storage}

_checks: dict[str, FileCheck] = {}
# Kinds a suspended member may still open (their own payslips and documents, §13.4).
_open_while_suspended: set[str] = set()
# What _verify returns for a genuine link whose time is up.
EXPIRED = object()


class DuplicateFileCheck(ValueError):
    pass


def register_file_check(kind: str, check: FileCheck, *, allow_suspended: bool = False) -> None:
    """Register who may open files of `kind` ("<app label>.<thing>", e.g. "hr.document").

    `check(user, company_id, object_id)` runs at download time and returns whether `user`
    may still open the file of that object; it is also the place to audit sensitive views.
    Only approved members get as far as the check, unless `allow_suspended`: then suspended
    members do too, and the check must limit them to their own files (their `has_perm` is
    False for everything while suspended).
    """
    app_label, dot, rest = kind.partition(".")
    if not dot or not rest:
        raise ValueError(f"File check kinds look like '<app>.<thing>', not {kind!r}.")
    if django_apps.ready and not any(
        config.label == app_label for config in django_apps.get_app_configs()
    ):
        raise ValueError(f"File check kind {kind!r} must start with an installed app's label.")
    if kind in _checks:
        raise DuplicateFileCheck(f"A file check named {kind!r} is already registered.")
    _checks[kind] = check
    if allow_suspended:
        _open_while_suspended.add(kind)


def registered_kinds() -> list[str]:
    return sorted(_checks)


def signed_url(
    file,
    *,
    user,
    company_id: int,
    check: str,
    ttl: int = DEFAULT_TTL,
    filename: str | None = None,
) -> str:
    """A link to `file` (a `FieldFile` of private or default storage) for `user`, valid for
    `ttl` seconds. `check` is "<kind>:<object id>"; `filename` is the name the browser saves
    it under (the stored name otherwise)."""
    kind, object_id = _parse_check(check)
    if kind not in _checks:
        raise ValueError(f"No file check registered for {kind!r}.")
    if not 0 < ttl <= MAX_TTL:
        raise ValueError("ttl must be between 1 second and 7 days.")
    name = getattr(file, "name", file)
    if not name:
        raise ValueError("This field has no file.")
    if PurePosixPath(name).suffix.lower() not in SERVED_TYPES:
        raise ValueError(f"Files like {name!r} are never served.")
    payload = {
        "n": name,
        "s": _storage_key(getattr(file, "storage", private_storage)),
        "u": user.pk,
        "c": company_id,
        "k": kind,
        "o": object_id,
        "e": int(time.time()) + ttl,
    }
    if filename:
        payload["f"] = filename
    token = signing.dumps(payload, salt=SALT, compress=True)
    return reverse("private-file", kwargs={"token": token})


@dataclass(frozen=True)
class _Grant:
    name: str
    storage: Storage
    user_id: int
    company_id: int
    kind: str
    object_id: int
    filename: str | None


class PrivateFileView(View):
    """`GET /api/v1/files/<token>/`. 404 for a bad link or lost access, 410 once expired."""

    http_method_names = ["get", "head"]

    def get(self, request, token: str):
        grant = _verify(token)
        if grant is None:
            raise Http404
        if grant is EXPIRED:
            return _plain(410, _("This link has expired. Open the file again from the app."))
        if not _may_open(grant):
            raise Http404
        extension = PurePosixPath(grant.name).suffix.lower()
        content_type, inline = SERVED_TYPES[extension]
        try:
            handle = grant.storage.open(grant.name, "rb")
        except (FileNotFoundError, OSError) as exc:
            raise Http404 from exc
        response = FileResponse(
            handle,
            content_type=content_type,
            as_attachment=not inline,
            filename=grant.filename or PurePosixPath(grant.name).name,
        )
        for header, value in SANDBOX_HEADERS.items():
            response[header] = value
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


@extend_schema_field(serializers.CharField(allow_null=True, help_text="Signed download link."))
class PrivateFileSerializerField(serializers.Field):
    """A read-only field that renders a private file as a signed link for the requesting user.

    `check` is a kind ("hr.document": the object id is the instance's pk) or a callable
    `(instance) -> "kind:id"`. The company is the instance's `company_id`, else the view's
    `company_id` URL argument.

        file = PrivateFileSerializerField(check="hr.document")
    """

    def __init__(
        self,
        *,
        check: str | Callable[[object], str],
        ttl: int = DEFAULT_TTL,
        filename: Callable[[object], str] | None = None,
        **kwargs,
    ):
        kwargs["read_only"] = True
        super().__init__(**kwargs)
        self.check = check
        self.ttl = ttl
        self.filename = filename
        self._instance = None

    def get_attribute(self, instance):
        self._instance = instance
        return super().get_attribute(instance)

    def to_representation(self, value):
        if not value:
            return None
        instance = self._instance
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        company_id = getattr(instance, "company_id", None)
        if company_id is None:
            view = self.context.get("view")
            company_id = int(view.kwargs["company_id"])
        check = self.check(instance) if callable(self.check) else f"{self.check}:{instance.pk}"
        return signed_url(
            value,
            user=user,
            company_id=company_id,
            check=check,
            ttl=self.ttl,
            filename=self.filename(instance) if self.filename else None,
        )


def _parse_check(check: str) -> tuple[str, int]:
    kind, colon, object_id = check.rpartition(":")
    if not colon or not kind or not object_id.isdigit():
        raise ValueError(f"A check looks like '<kind>:<object id>', not {check!r}.")
    return kind, int(object_id)


def _storage_key(storage: Storage) -> str:
    for key, known in STORAGES.items():
        if storage is known or type(storage) is type(known):
            return key
    raise ValueError("Only files in private or default storage can be signed.")


def _verify(token: str) -> _Grant | object | None:
    try:
        payload = signing.loads(token, salt=SALT)
        grant = _Grant(
            name=payload["n"],
            storage=STORAGES[payload["s"]],
            user_id=int(payload["u"]),
            company_id=int(payload["c"]),
            kind=payload["k"],
            object_id=int(payload["o"]),
            filename=payload.get("f"),
        )
        expires = int(payload["e"])
    except signing.BadSignature, KeyError, TypeError, ValueError:
        return None
    if PurePosixPath(grant.name).suffix.lower() not in SERVED_TYPES:
        return None
    if time.time() > expires:
        return EXPIRED
    return grant


def _may_open(grant: _Grant) -> bool:
    from apps.accounts.models import User
    from apps.members.models import Membership

    user = User.objects.filter(pk=grant.user_id, is_active=True).first()
    if user is None:
        return False
    statuses = [Membership.Status.APPROVED]
    if grant.kind in _open_while_suspended:
        statuses.append(Membership.Status.SUSPENDED)
    still_member = Membership.objects.filter(
        user=user,
        company_id=grant.company_id,
        company__is_active=True,
        status__in=statuses,
    ).exists()
    if not still_member:
        return False
    check = _checks.get(grant.kind)
    if check is None:
        logger.warning("No file check for %r; refusing the download", grant.kind)
        return False
    return bool(check(user, grant.company_id, grant.object_id))


def _plain(status: int, text: str) -> HttpResponse:
    response = HttpResponse(text, status=status, content_type="text/plain; charset=utf-8")
    for header, value in SANDBOX_HEADERS.items():
        response[header] = value
    return response
