"""Creating and setting up companies.

Every company starts the same way, whether an owner creates it in the owner bot or the
dashboard (`create_company`) or a platform admin adds it in Django admin
(`CompanyAdmin.save_model`): `setup_company` gives it the default roles, the default reminder
policy, a first branch named after it and, when given, its owner's membership, then sends
`company_created` on commit so every module adds its own defaults.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone as clock
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.companies import signals
from apps.companies.models import Branch, Company, validate_timezone
from apps.core.exceptions import DomainError
from apps.core.models import Language
from apps.core.money import Currency
from apps.core.signals import send_on_commit
from apps.members.models import AccessRole, Membership
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
    if owner is not None and not owner.is_platform_admin:
        owned = Membership.objects.filter(
            user=owner, status=Membership.Status.APPROVED, role__is_owner=True
        ).count()
        if owned >= settings.MAX_COMPANIES_PER_USER:
            raise DomainError(
                _("You already own %(count)d companies, the most one person can.")
                % {"count": owned}
            )
    fields = {
        "name": name[:200],
        "timezone": timezone,
        "default_language": language,
        "base_currency": base_currency,
    }
    with transaction.atomic():
        company = _create_with_slug(fields, slug)
        setup_company(company, by, owner=owner)
    return company


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
