"""Fixtures of the hiring tests, on top of HR's (`shop` with Chilonzor and Yunusobod, `staff`):

- `hirers`: who runs hiring. The owner and the manager (the Manager role: hr.hiring and
  members.approve, every branch); `scout` (hr.hiring and members.approve at Chilonzor only);
  `recruiter` (hr.hiring without members.approve, every branch); the accountant has no hr.hiring.
- `vacancy(**fields)`: an open vacancy at Chilonzor for pharmacists with three questions.
- `applicant(vacancy, telegram_id, **fields)`: someone who applied in the bot.
"""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from apps.accounts.models import User
from apps.hr.hiring import services
from apps.members.models import AccessRole, Position
from apps.members.permissions import Perm

QUESTIONS = [
    {"text": "Farmatsevtik ma’lumotingiz bormi?", "kind": "yes_no"},
    {
        "text": "Qaysi smena qulay?",
        "kind": "choice",
        "options": ["Kunduzgi", "Tungi", "Farqi yo‘q"],
    },
    {"text": "Necha yil tajribangiz bor?", "kind": "number", "required": False},
]


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 80)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def hirers(shop, staff, member, chilonzor, yunusobod):
    scout_role = AccessRole.objects.create(
        company=shop,
        name="Branch hiring",
        permissions=[
            Perm.DASHBOARD_ACCESS,
            Perm.HR_HIRING,
            Perm.MEMBERS_APPROVE,
            Perm.FINANCE_CLAIM,
        ],
    )
    recruiter_role = AccessRole.objects.create(
        company=shop,
        name="Recruiter",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.HR_HIRING, Perm.BRANCHES_ALL],
    )
    scout = member.registered(
        shop, scout_role.name, position=staff.office, home_branch=chilonzor, first_name="Kamol"
    )
    scout.branches.add(chilonzor)
    recruiter = member.registered(
        shop, recruiter_role.name, position=staff.office, home_branch=chilonzor, first_name="Rano"
    )
    recruiter.branches.add(chilonzor)
    cashier = Position.objects.create(
        company=shop,
        name="Cashier",
        order=3,
        role=AccessRole.objects.get(company=shop, name="Cashier"),
    )
    return SimpleNamespace(
        owner=staff.owner,
        manager=staff.manager,
        accountant=staff.accountant,
        scout=scout,
        recruiter=recruiter,
        pharmacist=staff.pharmacist,
        cashier=cashier,
    )


@pytest.fixture
def vacancy(shop, hirers, chilonzor):
    def make(**fields):
        fields.setdefault("title", "Farmatsevt")
        fields.setdefault("position", hirers.pharmacist)
        fields.setdefault("branch", chilonzor)
        fields.setdefault("questions", QUESTIONS)
        publish = fields.pop("publish", True)
        by = fields.pop("by", hirers.owner)
        return services.create_vacancy(shop, by=by, publish=publish, **fields)

    return make


@pytest.fixture
def committed(django_capture_on_commit_callbacks):
    """`with committed(): …` runs what the code left for after the commit: messages to the
    applicant, signals (the hire's welcome and HR profile), pulses."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def applicant(db):
    def make(vacancy, telegram_id=7001, *, name="Aziza Karimova", **fields):
        user = User.objects.filter(telegram_id=telegram_id).first() or User.objects.create(
            username=f"tg{telegram_id}",
            telegram_id=telegram_id,
            first_name=name.split()[0],
            last_name=name.split()[-1],
            telegram_username=f"user{telegram_id}",
            language=fields.pop("language", "uz"),
        )
        fields.setdefault("phone", f"+99890{telegram_id:07d}")
        fields.setdefault(
            "answers",
            [
                {"id": q["id"], "text": q["text"], "kind": q["kind"], "answer": "yes"}
                for q in vacancy.questions[:1]
            ],
        )
        return services.apply(vacancy.pk, user, name=name, **fields)

    return make
