"""Registrations of company setup with the shared registries.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.companies import queries, services
from apps.companies.audit_actions import CompanyAction
from apps.companies.models import Branch
from apps.console import registry
from apps.members import scope
from apps.members.permissions import Perm

audit_registry.register(CompanyAction)
audit_registry.register_target("branch", Perm.COMPANY_SETTINGS)
audit_registry.register_target("company", Perm.COMPANY_SETTINGS)

# Version keys: open dashboards refetch settings, branch lists and the checklist after a change.
registry.register_pulse("companies.settings", perm=None, count=None)
registry.register_pulse("companies.branches", perm=None, count=None)
registry.register_pulse("companies.setup", perm=None, count=None)

# "Get started" (§6.2): the steps this package owns. Other modules add theirs.
registry.register_setup_step(
    "companies.branches",
    perm=Perm.COMPANY_SETTINGS,
    order=10,
    label=_("Set up your branches"),
    description=_("Address, opening hours and the check-in circle on the map for each shop."),
    url="settings/branches",
    done=queries.branch_done,
)
registry.register_setup_step(
    "companies.invite",
    perm=Perm.MEMBERS_APPROVE,
    order=20,
    label=_("Invite your staff"),
    description=_("Share the invite link or hang the QR poster: people join from Telegram."),
    url="settings/invite",
    done=queries.staff_invited,
)
registry.register_setup_step(
    "companies.modules",
    perm=Perm.COMPANY_SETTINGS,
    order=40,
    label=_("Choose your modules"),
    description=_("Switch on only what you need: finance, sales, attendance, payroll and more."),
    url="settings/features",
    done=queries.modules_chosen,
)


def setup_brief(company, day, now, branch_ids) -> dict | None:
    """A line in the owner bot's /today (and briefings) until "Get started" is done."""
    if company.setup_completed_at is not None:
        return None
    steps = [
        step
        for step in registry.SETUP_STEPS
        if step.feature is None or company.has_feature(step.feature)
    ]
    done = sum(1 for step in steps if step.done(company))
    if not steps or done == len(steps):
        return None
    return {
        "emoji": "🚀",
        "title": str(_("Get started")),
        "lines": [str(_("%(done)d of %(total)d steps done")) % {"done": done, "total": len(steps)}],
    }


registry.register_brief_section(
    "companies.setup", perm=Perm.COMPANY_SETTINGS, order=900, build=setup_brief
)


def search_branches(member, q: str, limit: int) -> list[registry.SearchHit]:
    rows = scope.restrict(
        Branch.objects.for_company(member.company).filter(name__icontains=q),
        scope.branch_ids(member),
        field="id",
    ).order_by("-is_active", "order", "name")[:limit]
    return [
        registry.SearchHit(
            type="companies.branches",
            id=branch.pk,
            title=branch.name,
            subtitle=branch.address or branch.code or "",
            url=f"settings/branches?branch={branch.pk}",
        )
        for branch in rows
    ]


registry.register_search("companies.branches", perm=Perm.COMPANY_SETTINGS, search=search_branches)

# "Copy setup from another company" (§13.2): people, money and history never travel.
registry.register_copy_part(
    "companies.settings",
    label=_("Working days, report times and staff settings"),
    perm=Perm.COMPANY_SETTINGS,
    copy=services.copy_settings,
)
registry.register_copy_part(
    "companies.modules",
    label=_("Modules switched on"),
    perm=Perm.COMPANY_SETTINGS,
    copy=services.copy_modules,
)
