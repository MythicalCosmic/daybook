"""Base classes for every owner endpoint (`/api/v1/owner/…`).

    class ShiftViewSet(mixins.ListModelMixin, OwnerViewSet):
        perm = Perm.SALES_VIEW                                  # default for every action
        perms_by_action = {"verify": Perm.SALES_MANAGE}        # per action (or HTTP method)

        @action(detail=True, methods=["post"])
        def verify(self, request, company_id, pk):
            shift = services.verify(self.get_object(), by=self.membership)
            self.bump("sales.shifts")                           # after commit
            return Response(...)

What the base gives every company endpoint, in this order:

1. `OwnerJWTAuthentication` only: a mini app token (no `aud="dashboard"`) gets 401.
2. `OwnerCompanyAccess`: an approved membership in the URL's active company, else 404 (another
   company's id looks like a missing one); `dashboard.access`, else 403.
3. `HasPerm`: the spec in `perms_by_action[action]`, else `perm`; else 403.

It also sets `self.membership`, `self.company` and `self.branch_scope`, and adds them to the
serializer context. Services take `by=self.membership`; they audit with `audit.record` (or the
`audit()` helper here) and the view bumps pulse keys with `bump()`.
"""

from functools import cached_property

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions, generics, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from apps.audit import services as audit_services
from apps.console import pulse
from apps.console.perms import AllOf, AnyOf, PermSpec, holds
from apps.console.ranges import Range, RangeError, parse_range
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.signin.auth import OwnerJWTAuthentication

__all__ = [
    "AllOf",
    "AnyOf",
    "HasPerm",
    "OwnerAPIView",
    "OwnerCompanyAccess",
    "OwnerGenericAPIView",
    "OwnerUserAPIView",
    "OwnerViewSet",
    "RangeMixin",
    "audit",
    "bump",
]

MEMBERSHIP_RELATIONS = ("company", "user", "role", "position", "home_branch")


def owner_membership(user, company_id) -> Membership | None:
    """`user`'s approved membership in the active company `company_id`, or None."""
    return (
        Membership.objects.select_related(*MEMBERSHIP_RELATIONS)
        .filter(
            company_id=company_id,
            company__is_active=True,
            user=user,
            status=Membership.Status.APPROVED,
        )
        .first()
    )


class OwnerCompanyAccess(BasePermission):
    """Approved member of the URL's company with `dashboard.access`; sets `view.membership`."""

    def has_permission(self, request, view):
        membership = owner_membership(request.user, view.kwargs.get("company_id"))
        if membership is None:
            raise exceptions.NotFound
        if not membership.has_perm(Perm.DASHBOARD_ACCESS):
            raise exceptions.PermissionDenied(_("You don't have access to the dashboard."))
        view.membership = membership
        view.company = membership.company
        return True


class HasPerm(BasePermission):
    """The view's permission spec for this action; `HasPerm.of(spec)` fixes one instead
    (e.g. in `@action(permission_classes=...)`, after `OwnerCompanyAccess`)."""

    message = _("You don't have permission to do this.")
    spec: PermSpec = None
    fixed = False

    @classmethod
    def of(cls, spec: PermSpec) -> type[HasPerm]:
        return type("HasPerm", (cls,), {"spec": spec, "fixed": True})

    def has_permission(self, request, view):
        spec = self.spec if self.fixed else view.required_perm()
        return holds(view.membership, spec)


class OwnerMixin:
    authentication_classes = (OwnerJWTAuthentication,)
    permission_classes = (IsAuthenticated, OwnerCompanyAccess, HasPerm)
    perm: PermSpec = None
    perms_by_action: dict[str, PermSpec] = {}

    membership: Membership

    def required_perm(self) -> PermSpec:
        action = getattr(self, "action", None) or self.request.method.lower()
        return self.perms_by_action.get(action, self.perm)

    @property
    def branch_scope(self) -> list[int] | None:
        return scope.branch_ids(self.membership)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["membership"] = getattr(self, "membership", None)
        context["company"] = getattr(self, "company", None)
        return context

    def audit(self, action: str, target, **details):
        return audit(self.membership, action, target, **details)

    def bump(self, *keys: str) -> None:
        bump(self.company.pk, *keys)


class OwnerAPIView(OwnerMixin, APIView):
    def get_serializer_context(self):
        return {"request": self.request, "view": self, "format_kwarg": self.format_kwarg} | {
            "membership": self.membership,
            "company": self.company,
        }


class OwnerGenericAPIView(OwnerMixin, generics.GenericAPIView):
    pass


class OwnerViewSet(OwnerMixin, viewsets.GenericViewSet):
    """Add DRF's model mixins as needed; `perms_by_action` keys are the action names."""


class OwnerUserAPIView(APIView):
    """Owner endpoints outside a company (`me/`, `permissions/`): an owner token is enough."""

    authentication_classes = (OwnerJWTAuthentication,)
    permission_classes = (IsAuthenticated,)


class RangeMixin:
    """`self.range`: the request's `from`/`to`/`preset`/`compare` in the company's calendar."""

    @cached_property
    def range(self) -> Range:
        try:
            return parse_range(self.request.query_params, self.company, timezone.now())
        except RangeError as exc:
            raise exceptions.ValidationError({"range": [str(exc)]}) from exc


def audit(member: Membership, action: str, target, **details):
    """Record `action` on `target` by `member` in the audit log (inside the change's
    transaction, so both or neither stay)."""
    return audit_services.record(
        action, company_id=member.company_id, actor=member.user, target=target, **details
    )


def bump(company_id: int, *keys: str) -> None:
    """Bump pulse keys once the current transaction commits (at once outside one)."""
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))
