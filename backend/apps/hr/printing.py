"""Contract templates filled in for one person, and printed as a PDF (`apps.core.pdf`).

A template body is HTML cleaned by the knowledge base's allow-list (`apps.knowledge.sanitize`)
with `{{placeholders}}` from the fixed list below. Values are escaped before they go in, so a
name with "<" in it stays text. `{{salary_text}}` is filled only when the person printing holds
`payroll.view` (a blank line otherwise), and the PDF then remembers it carries pay.

    html = printing.contract_html(contract, template, by=member, language="uz")
"""

import html
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import translation
from django.utils.translation import gettext as _

from apps.core import pdf
from apps.core.exceptions import DomainError
from apps.hr import conf, integrations
from apps.hr.models import Contract, ContractTemplate
from apps.knowledge.sanitize import clean
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks.dates import MONTHS

# The fixed placeholder list (docs/PLAN-OWNER.md §3.11), in the order the editor offers them.
PLACEHOLDERS = (
    "company_name",
    "company_tin",
    "employee_full_name",
    "position",
    "branch",
    "starts_on",
    "ends_on",
    "probation_until",
    "weekly_hours",
    "salary_text",
    "today",
)
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
# What a value nobody filled prints as: a line to write on by hand.
BLANK = "_" * 16
MAX_BODY = 200_000
EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def clean_body(body: str) -> str:
    """The template body as it is stored: allowed HTML only, and only known placeholders."""
    text = clean(body or "")
    if not text:
        raise DomainError(_("Write the contract's text."))
    if len(text) > MAX_BODY:
        raise DomainError(_("The contract's text is too long."))
    unknown = sorted({name for name in PLACEHOLDER.findall(text) if name not in PLACEHOLDERS})
    if unknown:
        raise DomainError(
            _("Unknown placeholders: %(names)s.")
            % {"names": ", ".join("{{" + name + "}}" for name in unknown)}
        )
    return text


def long_date(day: date | None, language: str) -> str:
    """A date as a contract writes it: "2026-yil 25-oktabr" in Uzbek, the day, the month's
    name and the year in Russian and English ("" without a day)."""
    if day is None:
        return ""
    if language == "uz":
        return f"{day.year}-yil {day.day}-{MONTHS['uz'][day.month - 1]}"
    if language == "ru":
        return f"{day.day} {MONTHS['ru'][day.month - 1]} {day.year} г."
    return f"{day.day} {EN_MONTHS[day.month - 1]} {day.year}"


@dataclass(frozen=True)
class Filled:
    html: str
    has_salary: bool
    # Placeholders the text uses that had nothing to fill in (printed as a blank line).
    empty: tuple[str, ...]


def values(
    membership: Membership,
    contract: Contract | None,
    *,
    by: Membership | None,
    language: str,
    today: date,
) -> dict[str, str]:
    """Every placeholder's text for this person (and contract, when there is one)."""
    settings = conf.get_settings(membership.company)
    position = (contract.position if contract and contract.position_id else None) or (
        membership.position
    )
    profile_name = " ".join(
        part
        for part in (
            membership.last_name,
            membership.first_name,
            getattr(getattr(membership, "profile", None), "middle_name", ""),
        )
        if part
    )
    salary = ""
    if by is None or by.has_perm(Perm.PAYROLL_VIEW):
        salary = integrations.salary_text(
            membership, contract.starts_on if contract else today, language
        )
    hours = ""
    if contract is not None and contract.weekly_hours is not None:
        hours = _hours(contract.weekly_hours, language)
    return {
        "company_name": settings.employer_name or membership.company.name,
        "company_tin": settings.employer_tin,
        "employee_full_name": profile_name or str(membership),
        "position": position.name if position else "",
        "branch": membership.home_branch.name if membership.home_branch_id else "",
        "starts_on": long_date(contract.starts_on if contract else None, language),
        "ends_on": long_date(contract.ends_on if contract else None, language),
        "probation_until": long_date(contract.probation_until if contract else None, language),
        "weekly_hours": hours,
        "salary_text": salary,
        "today": long_date(today, language),
    }


def fill(body: str, found: dict[str, str]) -> Filled:
    """`body` with every placeholder replaced by its (escaped) value."""
    empty: list[str] = []

    def replace(match: re.Match) -> str:
        name = match.group(1)
        value = found.get(name, "")
        if not value:
            if name not in empty:
                empty.append(name)
            return BLANK
        return html.escape(value)

    text = PLACEHOLDER.sub(replace, body)
    uses_salary = "salary_text" in PLACEHOLDER.findall(body)
    return Filled(text, uses_salary and bool(found.get("salary_text")), tuple(empty))


def contract_html(
    membership: Membership,
    template: ContractTemplate,
    *,
    contract: Contract | None,
    by: Membership | None,
    today: date,
    body: str | None = None,
) -> Filled:
    """The template (or an unsaved `body`) filled in for `membership`, in the template's
    language."""
    language = template.language if template else membership.company.default_language
    with translation.override(language):
        found = values(membership, contract, by=by, language=language, today=today)
    return fill(clean_body(body) if body is not None else template.body, found)


def contract_pdf(contract: Contract, template: ContractTemplate, filled: Filled) -> bytes:
    title = template.name
    if contract.number:
        title = f"{title} · {contract.number}"
    return pdf.render_pdf(
        "hr/contract.html",
        {"company": contract.company, "title": title, "body": filled.html},
        language=template.language,
    )


def _hours(value: Decimal, language: str) -> str:
    text = f"{value.normalize():f}"
    return text.replace(".", ",") if language in ("uz", "ru") else text
