import pytest
from asgiref.sync import sync_to_async

from apps.companies.tests.factories import CompanyFactory
from apps.members.models import AccessRole, Membership
from apps.members.tests.factories import MembershipFactory


@pytest.fixture
def company(db):
    return CompanyFactory()


@pytest.fixture
def other_company(db):
    return CompanyFactory()


class MemberMaker:
    """Makes members holding one of the company's default roles, approved unless told otherwise."""

    def __call__(self, company, role_name="Employee", **kwargs) -> Membership:
        kwargs.setdefault("status", Membership.Status.APPROVED)
        role = AccessRole.objects.get(company=company, name=role_name)
        return MembershipFactory(company=company, role=role, **kwargs)

    async def acreate(self, company, role_name="Employee", **kwargs) -> Membership:
        return await sync_to_async(self)(company, role_name, **kwargs)


@pytest.fixture
def member(db):
    return MemberMaker()


@pytest.fixture
def sent_messages(monkeypatch):
    """Telegram messages the backend tried to send, captured instead of sent."""
    sent = []

    def record(bot, chat_id, text, reply_markup=None):
        sent.append({"bot": bot, "chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    monkeypatch.setattr("apps.notifications.telegram.send_message", record)
    return sent
