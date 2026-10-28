"""Creating and setting up companies.

Every company starts the same way, whether an owner creates it in the owner bot or the
dashboard (`create_company`) or a platform admin adds it in Django admin
(`CompanyAdmin.save_model`): `setup_company` gives it the default roles, the default reminder
policy, a first branch named after it and, when given, its owner's membership, then sends
`company_created` on commit so every module adds its own defaults.

The owner's own changes (Package A, docs/PLAN-OWNER.md §4.4), each audited with `by`:

    create_company_for(user, *, name, …, signup_code, copy_from, parts)   bot /new, dashboard
    update_settings(company, *, by, **fields)       base currency locked once money is booked
    set_logo(company, *, by, logo)                  a sanitized picture, or None to remove it
    set_features(company, *, by, features)          newly enabled modules get their defaults
    create_branch / update_branch / deactivate_branch / activate_branch / reorder_branches
    regenerate_invite(company, *, by)
    dismiss_setup / resume_setup                    the "Get started" checklist
"""

import importlib
import importlib.util
import re
from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone as clock
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.companies import signals
from apps.companies.audit_actions import CompanyAction
from apps.companies.models import Branch, Company, Feature, validate_timezone
from apps.core.exceptions import DomainError
from apps.core.models import Language
from apps.core.money import Currency
from apps.core.signals import send_on_commit
from apps.members.models import AccessRole, Membership
from apps.members.positions import create_default_positions
from apps.members.services import create_default_roles
from apps.reminders.policies import default_policy

# Uzbek and Russian Cyrillic in Latin letters, for slugs ("Ромашка" -> "romashka").
_CYRILLIC = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ",
        (
            *("a", "b", "v", "g", "d", "e", "yo", "j", "z", "i", "y", "k", "l", "m", "n", "o"),
            *("p", "r", "s", "t", "u", "f", "x", "ts", "ch", "sh", "sh", "", "i", "", "e"),
            *("yu", "ya", "o", "q", "g", "h"),
        ),
        strict=True,
    )
)
SLUG_ATTEMPTS = 20


def create_company(
    *,
    name: str,
    timezone: str = "Asia/Tashkent",
    language: str = Language.UZ,
    owner: User | None = None,
    slug: str | None = None,
    by: Membership | None = None,
    base_currency: str = Currency.UZS,
) -> Company:
    """Create a company and set it up (`setup_company`). Without a slug one is made from the
    name. An owner who isn't a platform admin may own at most MAX_COMPANIES_PER_USER."""
    name = name.strip()
    if not name:
        raise DomainError(_("Give the company a name."))
    try:
        validate_timezone(timezone)
    except ValidationError as exc:
        raise DomainError(_("Pick a timezone from the list.")) from exc
    if language not in Language.values:
        raise DomainError(_("Pick one of the languages offered."))
    if base_currency not in Currency.values:
        raise DomainError(_("Pick one of the currencies offered."))
    fields = {
        "name": name[:200],
        "timezone": timezone,
        "default_language": language,
        "base_currency": base_currency,
    }
    with transaction.atomic():
        if owner is not None and not owner.is_platform_admin:
            _ensure_may_own_another(owner)
        company = _create_with_slug(fields, slug)
        setup_company(company, by, owner=owner)
    return company


def _ensure_may_own_another(owner: User) -> None:
    """MAX_COMPANIES_PER_USER. The owner's row is locked, so two companies created at the
    same moment can't both slip under the limit."""
    from apps.companies.queries import owned_count

    User.objects.select_for_update().filter(pk=owner.pk).first()
    owned = owned_count(owner)
    if owned >= settings.MAX_COMPANIES_PER_USER:
        raise DomainError(
            _("You already own %(count)d companies, the most one person can.") % {"count": owned}
        )


@transaction.atomic
def setup_company(company: Company, by: Membership | None = None, *, owner: User | None = None):
    """Give a new company everything it starts with, and announce it. Safe to run again:
    nothing that already exists is made twice."""
    create_default_roles(company)
    default_policy(company.pk)
    branch = company.branches.order_by("pk").first()
    if branch is None:
        branch = Branch.objects.create(company=company, name=company.name[:100])
    if owner is not None:
        _make_owner(company, owner, branch)
    send_on_commit(signals.company_created, sender=Company, company=company, by=by)
    return company


def find_by_invite(start_param: str) -> Company:
    """Resolve a /start deep-link parameter to an active company."""
    code = start_param.removeprefix(Company.INVITE_PREFIX)
    company = None
    if code != start_param:
        company = Company.objects.filter(invite_code=code, is_active=True).first()
    if company is None:
        raise DomainError(
            _("This invite link is invalid or has expired. Ask your manager for a new one.")
        )
    return company


def slug_for(name: str) -> str:
    """A URL-safe slug for a company name, Cyrillic included."""
    latin = "".join(_CYRILLIC.get(char, char) for char in name.lower())
    latin = re.sub(r"[ʻʼ‘’`']", "", latin)  # the apostrophes of Uzbek Latin
    return slugify(latin)[:40].strip("-") or "company"


def _create_with_slug(fields: dict, slug: str | None) -> Company:
    if slug:
        return Company.objects.create(slug=slug, **fields)
    base = slug_for(fields["name"])
    for attempt in range(SLUG_ATTEMPTS):
        candidate = base if attempt == 0 else f"{base}-{attempt + 1}"
        if Company.objects.filter(slug=candidate).exists():
            continue
        try:
            with transaction.atomic():
                return Company.objects.create(slug=candidate, **fields)
        except IntegrityError:
            continue  # someone took it a moment ago
    raise DomainError(_("Couldn't find a free web address for this name. Try another name."))


def _make_owner(company: Company, owner: User, branch: Branch) -> Membership:
    role = AccessRole.objects.for_company(company).filter(is_owner=True).order_by("pk").first()
    now = clock.now()
    membership, _created = Membership.objects.update_or_create(
        company=company,
        user=owner,
        defaults={
            "status": Membership.Status.APPROVED,
            "role": role,
            "first_name": owner.first_name[:100],
            "last_name": owner.last_name[:100],
            "decided_at": now,
            "onboarded_at": now,
            "home_branch": branch,
        },
    )
    membership.branches.set([branch])
    return membership


# A new company from the owner bot (/new) or the dashboard ("New company") -------------------


def create_company_for(
    user: User,
    *,
    name: str,
    timezone: str = "Asia/Tashkent",
    language: str = Language.UZ,
    base_currency: str = Currency.UZS,
    signup_code: str | None = None,
    copy_from: Company | None = None,
    parts: list[str] | tuple[str, ...] = (),
) -> tuple[Company, dict[str, int]]:
    """Create a company owned by `user`, honouring `COMPANY_SIGNUP` (a signup code is used up
    when the policy needs one) and `MAX_COMPANIES_PER_USER`, and copy the chosen setup parts
    from another of their companies. Everything or nothing. Returns (company, rows copied per
    part)."""
    from apps.console import registry
    from apps.signin import signup

    with transaction.atomic():
        signup.admit(user, signup_code)
        company = create_company(
            name=name, timezone=timezone, language=language, owner=user, base_currency=base_currency
        )
        owner = Membership.objects.select_related("company", "role").get(company=company, user=user)
        audit.record(CompanyAction.CREATED, company_id=company.pk, actor=user, target=company)
        copied: dict[str, int] = {}
        if copy_from is not None and parts:
            try:
                copied = registry.run_copy(copy_from, company, list(parts), by=owner)
            except registry.RegistryError as exc:
                raise DomainError(
                    _("Some of that setup can't be copied from %(company)s.")
                    % {"company": copy_from.name}
                ) from exc
            audit.record(
                CompanyAction.SETUP_COPIED,
                company_id=company.pk,
                actor=user,
                target=company,
                source=copy_from.name,
                parts=copied,
            )
        # A pharmacy's usual job titles, unless positions were copied from another company.
        create_default_positions(company)
    return company, copied


# Settings ---------------------------------------------------------------------------------

SETTINGS_FIELDS = (
    "name",
    "timezone",
    "default_language",
    "base_currency",
    "workdays",
    "morning_report_at",
    "evening_report_at",
    "morning_digest",
    "rejoin_cooldown_hours",
    "owner_sees_personal_tasks",
    "team_directory_phones",
)
MAX_REJOIN_COOLDOWN_HOURS = 24 * 30


def base_currency_locked(company: Company) -> bool:
    """The base currency can't change once anything is booked in the finance ledger."""
    from apps.finance.queries import has_ledger_rows

    return has_ledger_rows(company)


def update_settings(company: Company, *, by: Membership, **fields) -> Company:
    """Change the company's settings (only the fields given). Raises DomainError."""
    unknown = set(fields) - set(SETTINGS_FIELDS)
    if unknown:
        raise DomainError(
            _("These settings can't be changed here: %(names)s.")
            % {"names": ", ".join(sorted(unknown))}
        )
    clean = {name: _clean_setting(name, value) for name, value in fields.items()}
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        if (
            "base_currency" in clean
            and clean["base_currency"] != company.base_currency
            and base_currency_locked(company)
        ):
            raise DomainError(
                _(
                    "The base currency stays %(currency)s: money is already booked in it. "
                    "Reports and the ledger add up in one currency."
                )
                % {"currency": company.base_currency}
            )
        morning = clean.get("morning_report_at", company.morning_report_at)
        evening = clean.get("evening_report_at", company.evening_report_at)
        if morning == evening:
            raise DomainError(_("The morning and evening reports need different times."))
        if "base_currency" in clean and clean["base_currency"] != company.base_currency:
            # Nothing is booked yet: finance moves its default cash desk and terminal along
            # (and refuses, rolling this back, if something got booked meanwhile).
            from apps.finance.services import rebase_default_accounts

            rebase_default_accounts(company, currency=clean["base_currency"], by=by)
        before = audit.snapshot(company)
        for name, value in clean.items():
            setattr(company, name, value)
        company.save(update_fields=[*clean, "updated_at"])
        if changes := audit.diff(before, audit.snapshot(company)):
            audit.record(
                CompanyAction.SETTINGS_CHANGED,
                company_id=company.pk,
                actor=by.user,
                target=company,
                changes=changes,
            )
    return company


def _clean_setting(name: str, value):
    if name == "name":
        value = (value or "").strip()
        if not value:
            raise DomainError(_("Give the company a name."))
        return value[:200]
    if name == "timezone":
        try:
            validate_timezone(value)
        except ValidationError as exc:
            raise DomainError(_("Pick a timezone from the list.")) from exc
        return value
    if name == "default_language":
        if value not in Language.values:
            raise DomainError(_("Pick one of the languages offered."))
        return value
    if name == "base_currency":
        if value not in Currency.values:
            raise DomainError(_("Pick one of the currencies offered."))
        return value
    if name == "workdays":
        days = sorted({int(day) for day in value or ()})
        if not days or any(day < 0 or day > 6 for day in days):
            raise DomainError(_("Pick at least one working day."))
        return days
    if name in ("morning_report_at", "evening_report_at"):
        if not isinstance(value, time):
            raise DomainError(_("Pick a time for the report."))
        return value.replace(second=0, microsecond=0)
    if name == "rejoin_cooldown_hours":
        hours = int(value)
        if hours < 0 or hours > MAX_REJOIN_COOLDOWN_HOURS:
            raise DomainError(_("The waiting time is between 0 and 720 hours."))
        return hours
    return bool(value)


def set_logo(company: Company, *, by: Membership, logo) -> Company:
    """A new logo (already through `apps.core.uploads.sanitize_image`), or None to remove it."""
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        old = company.logo.name if company.logo else ""
        if logo is None:
            company.logo = ""
        else:
            company.logo.save(logo.name, logo, save=False)
        company.save(update_fields=["logo", "updated_at"])
        audit.record(
            CompanyAction.LOGO_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=company,
            removed=logo is None,
        )
    if old:
        storage = company.logo.storage
        transaction.on_commit(lambda: storage.delete(old))
    return company


# Modules ----------------------------------------------------------------------------------

# Which apps' `defaults.ensure` a module switch brings in (HR covers the lifecycle app too).
FEATURE_APPS: dict[str, tuple[str, ...]] = {
    Feature.FINANCE: ("finance",),
    Feature.SALES: ("finance", "sales"),
    Feature.STOCK: ("inventory",),
    Feature.ATTENDANCE: ("attendance",),
    Feature.HR: ("hr", "lifecycle"),
    Feature.PAYROLL: ("payroll",),
    Feature.AI: ("ai",),
    Feature.RECOGNITION: ("recognition",),
}


def set_features(company: Company, *, by: Membership | None, features) -> Company:
    """Switch modules on and off (`Company.features`, the only module switch). A module
    switched on gets its defaults (payment methods, categories, leave types…); one switched off
    keeps its data, hidden until it comes back."""
    wanted = list(dict.fromkeys(str(feature) for feature in features))
    if any(feature not in Feature.values for feature in wanted):
        raise DomainError(_("Pick modules from the list."))
    ordered = [feature for feature in Feature.values if feature in wanted]
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        before = list(company.features)
        if before == ordered:
            return company
        company.features = ordered
        company.save(update_fields=["features", "updated_at"])
        switched_on = [feature for feature in ordered if feature not in before]
        for label in dict.fromkeys(app for feature in switched_on for app in FEATURE_APPS[feature]):
            _ensure_defaults(label, company)
        audit.record(
            CompanyAction.FEATURES_CHANGED,
            company_id=company.pk,
            actor=by.user if by else None,
            target=company,
            changes={"features": [before, ordered]},
            on=switched_on,
            off=[feature for feature in before if feature not in ordered],
        )
    return company


def _ensure_defaults(app_label: str, company: Company) -> None:
    name = f"apps.{app_label}.defaults"
    if importlib.util.find_spec(name) is None:
        return
    ensure = getattr(importlib.import_module(name), "ensure", None)
    if callable(ensure):
        ensure(company)


# Branches ---------------------------------------------------------------------------------

BRANCH_FIELDS = (
    "name",
    "code",
    "address",
    "phone",
    "latitude",
    "longitude",
    "geofence_m",
    "opens_at",
    "closes_at",
    "open_weekdays",
    "manager",
    "cash_limit",
)
GEOFENCE_RANGE = (25, 5000)
CODE_PATTERN = re.compile(r"^[A-Z0-9]{1,8}$")


def create_branch(company: Company, *, by: Membership, **fields) -> Branch:
    """A new branch at the end of the list."""
    with transaction.atomic():
        _lock_company(company.pk)
        branch = Branch(company=company)
        _apply_branch(branch, fields)
        last = (
            Branch.objects.for_company(company)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        branch.order = (last or 0) + 1
        _save_branch(branch)
        audit.record(
            CompanyAction.BRANCH_CREATED,
            company_id=company.pk,
            actor=by.user,
            target=branch,
            after=audit.snapshot(branch),
        )
    return branch


def update_branch(branch: Branch, *, by: Membership, **fields) -> Branch:
    with transaction.atomic():
        # The company row first, as create and close do: names and codes stay unique even
        # when two people rename branches at the same moment.
        _lock_company(branch.company_id)
        branch = Branch.objects.select_for_update().get(pk=branch.pk)
        before = audit.snapshot(branch)
        _apply_branch(branch, fields)
        _save_branch(branch)
        if changes := audit.diff(before, audit.snapshot(branch)):
            audit.record(
                CompanyAction.BRANCH_CHANGED,
                company_id=branch.company_id,
                actor=by.user,
                target=branch,
                changes=changes,
            )
    return branch


def deactivate_branch(branch: Branch, *, by: Membership) -> Branch:
    """Close a branch: it leaves pickers and new work, its history stays. The last open
    branch can't be closed."""
    with transaction.atomic():
        # Two people closing the last two open branches at once must not both succeed: the
        # company row makes the second one wait and then see the first one's change.
        _lock_company(branch.company_id)
        branch = Branch.objects.select_for_update().get(pk=branch.pk)
        if not branch.is_active:
            return branch
        others = (
            Branch.objects.for_company(branch.company_id)
            .filter(is_active=True)
            .exclude(pk=branch.pk)
        )
        if not others.exists():
            raise DomainError(_("A company needs at least one open branch."))
        branch.is_active = False
        branch.save(update_fields=["is_active", "updated_at"])
        audit.record(
            CompanyAction.BRANCH_DEACTIVATED,
            company_id=branch.company_id,
            actor=by.user,
            target=branch,
        )
    return branch


def activate_branch(branch: Branch, *, by: Membership) -> Branch:
    with transaction.atomic():
        branch = Branch.objects.select_for_update().get(pk=branch.pk)
        if branch.is_active:
            return branch
        branch.is_active = True
        branch.save(update_fields=["is_active", "updated_at"])
        audit.record(
            CompanyAction.BRANCH_ACTIVATED,
            company_id=branch.company_id,
            actor=by.user,
            target=branch,
        )
    return branch


def reorder_branches(company: Company, *, by: Membership, ids: list[int]) -> list[Branch]:
    """Put branches in this order (every branch id of the company, each once)."""
    with transaction.atomic():
        _lock_company(company.pk)
        branches = {b.pk: b for b in Branch.objects.select_for_update().for_company(company)}
        if sorted(ids) != sorted(branches) or len(set(ids)) != len(ids):
            raise DomainError(_("List every branch once to reorder them."))
        changed = []
        for position, pk in enumerate(ids, start=1):
            branch = branches[pk]
            if branch.order != position:
                branch.order = position
                changed.append(branch)
        Branch.objects.bulk_update(changed, ["order"])
        if changed:
            audit.record(
                CompanyAction.BRANCHES_REORDERED,
                company_id=company.pk,
                actor=by.user,
                target=company,
                order=ids,
            )
    return [branches[pk] for pk in ids]


def _lock_company(company_id: int) -> None:
    """Every branch write takes the company row first, so they queue up in one order."""
    Company.objects.select_for_update().filter(pk=company_id).values_list("pk", flat=True).first()


def _save_branch(branch: Branch) -> None:
    """Save, turning the database's unique-name guard into the message people understand."""
    try:
        with transaction.atomic():
            branch.save()
    except IntegrityError as exc:
        raise DomainError(
            _("Another branch is already called %(name)s.") % {"name": branch.name}
        ) from exc


def _apply_branch(branch: Branch, fields: dict) -> None:
    unknown = set(fields) - set(BRANCH_FIELDS)
    if unknown:
        raise DomainError(
            _("These fields can't be changed here: %(names)s.")
            % {"names": ", ".join(sorted(unknown))}
        )
    for name, value in fields.items():
        setattr(branch, name, _clean_branch_field(branch, name, value))
    if (branch.latitude is None) != (branch.longitude is None):
        raise DomainError(_("Set both the latitude and the longitude, or neither."))
    if (branch.opens_at is None) != (branch.closes_at is None):
        raise DomainError(_("Set both the opening and the closing time, or neither."))
    taken = Branch.objects.for_company(branch.company_id).exclude(pk=branch.pk)
    if taken.filter(name__iexact=branch.name).exists():
        raise DomainError(_("Another branch is already called %(name)s.") % {"name": branch.name})
    if branch.code and taken.filter(code=branch.code).exists():
        raise DomainError(
            _("Another branch already uses the code %(code)s.") % {"code": branch.code}
        )


def _clean_branch_field(branch: Branch, name: str, value):
    if name == "name":
        value = (value or "").strip()
        if not value:
            raise DomainError(_("Give the branch a name."))
        return value[:100]
    if name == "code":
        value = (value or "").strip().upper()
        if value and not CODE_PATTERN.match(value):
            raise DomainError(_("A branch code is up to 8 Latin letters or digits, like CHL."))
        return value
    if name in ("address", "phone"):
        limit = 255 if name == "address" else 20
        return (value or "").strip()[:limit]
    if name in ("latitude", "longitude"):
        if value is None or value == "":
            return None
        number = Decimal(str(value)).quantize(Decimal("0.000001"))
        bound = 90 if name == "latitude" else 180
        if abs(number) > bound:
            raise DomainError(_("That point isn't on the map."))
        return number
    if name == "geofence_m":
        metres = int(value)
        low, high = GEOFENCE_RANGE
        if metres < low or metres > high:
            raise DomainError(_("The check-in radius is between 25 and 5 000 metres."))
        return metres
    if name in ("opens_at", "closes_at"):
        return value.replace(second=0, microsecond=0) if value else None
    if name == "open_weekdays":
        days = sorted({int(day) for day in value or ()})
        if any(day < 0 or day > 6 for day in days):
            raise DomainError(_("Pick weekdays from Monday to Sunday."))
        return days
    if name == "manager":
        if value is None:
            return None
        manager = (
            value if isinstance(value, Membership) else Membership.objects.filter(pk=value).first()
        )
        if (
            manager is None
            or manager.company_id != branch.company_id
            or manager.status != Membership.Status.APPROVED
        ):
            raise DomainError(_("Pick a manager who works in this company."))
        return manager
    if name == "cash_limit":
        if value is None or value == "":
            return None
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
        if amount < 0:
            raise DomainError(_("The cash limit can't be negative."))
        return amount
    return value


# Invite and Get started -------------------------------------------------------------------


def regenerate_invite(company: Company, *, by: Membership) -> Company:
    """A new invite link; the old one (and printed posters) stop working at once."""
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        company.regenerate_invite_code()
        audit.record(
            CompanyAction.INVITE_REGENERATED, company_id=company.pk, actor=by.user, target=company
        )
    return company


def dismiss_setup(company: Company, *, by: Membership) -> Company:
    """Hide "Get started" for everyone in the company (it can come back)."""
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        if company.setup_completed_at is None:
            company.setup_completed_at = clock.now()
            company.save(update_fields=["setup_completed_at", "updated_at"])
            audit.record(
                CompanyAction.SETUP_DISMISSED, company_id=company.pk, actor=by.user, target=company
            )
    return company


def resume_setup(company: Company, *, by: Membership) -> Company:
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        if company.setup_completed_at is not None:
            company.setup_completed_at = None
            company.save(update_fields=["setup_completed_at", "updated_at"])
            audit.record(
                CompanyAction.SETUP_RESUMED, company_id=company.pk, actor=by.user, target=company
            )
    return company


# Copy setup parts (registered in hooks.py) -------------------------------------------------

COPIED_SETTINGS = (
    "workdays",
    "morning_report_at",
    "evening_report_at",
    "morning_digest",
    "rejoin_cooldown_hours",
    "owner_sees_personal_tasks",
    "team_directory_phones",
)


def copy_settings(source: Company, target: Company, by: Membership) -> int:
    """Working days, report times and the people switches; returns 1."""
    update_settings(target, by=by, **{name: getattr(source, name) for name in COPIED_SETTINGS})
    return 1


def copy_modules(source: Company, target: Company, by: Membership) -> int:
    """The modules switched on in `source`; returns how many came on."""
    before = set(target.features)
    company = set_features(target, by=by, features=[*target.features, *source.features])
    return len(set(company.features) - before)
