"""A one-off survey after the launch: everyone checks their branch, department and job title in
the employee bot (the owner's request, 2026-11-02: some details were entered wrong at launch).

    python manage.py send_profile_fix --company 1          # creates the branches, sends to all

Every choice travels in the button (`ProfileFix`), nothing is kept between taps. Saving sets
the person's branch (only that one, as their home branch), department and job title. Access is
never raised by a self-chosen title: the title's role follows only for titles whose role can't
manage people or open the dashboard, and an owner's role never changes.
"""

import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.db import transaction

from apps.companies.models import Branch, Company
from apps.members.callbacks import ProfileFix
from apps.members.models import Department, Membership, Position
from apps.members.permissions import Perm

BRANCH_NAMES = ("Asosiy", "G‘alaba")
GONE_STATUSES = (Membership.Status.LEFT, Membership.Status.BLOCKED, Membership.Status.REJECTED)
# Titles nobody should pick for themselves in a survey.
HIDDEN_TITLES = ("Test",)
# A role that can do any of these is never given by a self-chosen title.
GUARDED = (Perm.MEMBERS_MANAGE, Perm.DASHBOARD_ACCESS, Perm.TASKS_VIEW_ALL)

INTRO = (
    "Assalomu alaykum!\n\n"
    "Ishga tushirishda ba’zi ma’lumotlar noto‘g‘ri kiritilgan edi. Iltimos, ularni qayta "
    "tanlang, bir daqiqa ham olmaydi.\n\n"
    "<b>1/3.</b> Qaysi filialda ishlaysiz?"
)
ASK_DEPARTMENT = "<b>2/3.</b> Qaysi bo‘limda ishlaysiz?"
ASK_TITLE = "<b>3/3.</b> Lavozimingiz qaysi?"
NO_DEPARTMENT = "Bo‘limsiz"
SAVE = "Tasdiqlash"
REDO = "Qaytadan"
SAVED = "Rahmat! Ma’lumotlaringiz saqlandi:"
GONE = "Bu xabar endi amal qilmaydi."


def branches(company: Company) -> list[Branch]:
    found = {b.name: b for b in Branch.objects.filter(company=company, name__in=BRANCH_NAMES)}
    return [found[name] for name in BRANCH_NAMES if name in found]


def ensure_branches(company: Company) -> list[Branch]:
    """The launch's single branch "Main" becomes Asosiy (its people, tasks and data stay with
    it); G‘alaba is added."""
    if not Branch.objects.filter(company=company, name=BRANCH_NAMES[0]).exists():
        Branch.objects.filter(company=company, name="Main").update(name=BRANCH_NAMES[0])
    for name in BRANCH_NAMES:
        Branch.objects.get_or_create(company=company, name=name)
    return branches(company)


def departments(company: Company) -> list[Department]:
    return list(Department.objects.filter(company=company).order_by("name"))


def titles(company: Company) -> list[Position]:
    return [
        p
        for p in Position.objects.filter(company=company, is_active=True).order_by("pk")
        if p.name not in HIDDEN_TITLES
    ]


def _rows(buttons: list[InlineKeyboardButton], width: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + width] for i in range(0, len(buttons), width)]


def branch_keyboard(company: Company) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=b.name, callback_data=ProfileFix(step="b", b=b.pk).pack())
        for b in branches(company)
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons))


def department_keyboard(company: Company, b: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=d.name, callback_data=ProfileFix(step="d", b=b, d=d.pk).pack())
        for d in departments(company)
    ]
    buttons.append(
        InlineKeyboardButton(text=NO_DEPARTMENT, callback_data=ProfileFix(step="d", b=b).pack())
    )
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons))


def title_keyboard(company: Company, b: int, d: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=p.name, callback_data=ProfileFix(step="p", b=b, d=d, p=p.pk).pack()
        )
        for p in titles(company)
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons))


def summary(company: Company, b: int, d: int, p: int) -> str:
    branch = Branch.objects.filter(company=company, pk=b).first()
    department = Department.objects.filter(company=company, pk=d).first() if d else None
    title = Position.objects.filter(company=company, pk=p).first()
    return (
        f"Filial: <b>{html.escape(branch.name if branch else '—')}</b>\n"
        f"Bo‘lim: <b>{html.escape(department.name if department else NO_DEPARTMENT)}</b>\n"
        f"Lavozim: <b>{html.escape(title.name if title else '—')}</b>"
    )


def confirm_keyboard(b: int, d: int, p: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=SAVE, callback_data=ProfileFix(step="ok", b=b, d=d, p=p).pack()
                ),
                InlineKeyboardButton(text=REDO, callback_data=ProfileFix(step="redo").pack()),
            ]
        ]
    )


def member_for(user, company_id: int | None = None) -> Membership | None:
    """The person's membership in a company that runs the survey (has its branches)."""
    rows = Membership.objects.filter(user=user).exclude(status__in=GONE_STATUSES)
    rows = rows.filter(company__branches__name=BRANCH_NAMES[0]).select_related("company", "role")
    if company_id:
        rows = rows.filter(company_id=company_id)
    return rows.order_by("pk").first()


def _guarded(role) -> bool:
    return role is None or role.is_owner or any(role.grants(perm) for perm in GUARDED)


@transaction.atomic
def apply(membership: Membership, *, b: int, d: int, p: int) -> bool:
    """Save the person's choices; False when an id isn't one of the company's offered ones."""
    from apps.members.services import title_role

    company = membership.company
    branch = Branch.objects.filter(company=company, pk=b, name__in=BRANCH_NAMES).first()
    department = Department.objects.filter(company=company, pk=d).first() if d else None
    title = next((t for t in titles(company) if t.pk == p), None)
    if branch is None or title is None or (d and department is None):
        return False
    membership = (
        Membership.objects.select_for_update(of=("self",))
        .select_related("role")
        .get(pk=membership.pk)
    )
    membership.department = department
    membership.position = title
    membership.home_branch = branch
    fields = ["department", "position", "home_branch"]
    new_role = title_role(title, company)
    owner = membership.role is not None and membership.role.is_owner
    keeps_power = membership.role is not None and _guarded(membership.role)
    if not owner and not keeps_power and new_role is not None and not _guarded(new_role):
        membership.role = new_role
        fields.append("role")
    membership.save(update_fields=[*fields, "updated_at"])
    membership.branches.set([branch])
    return True


def recipients(company: Company) -> list[Membership]:
    return list(
        Membership.objects.filter(company=company, user__telegram_id__isnull=False)
        .exclude(status__in=GONE_STATUSES)
        .select_related("user")
        .order_by("pk")
    )
