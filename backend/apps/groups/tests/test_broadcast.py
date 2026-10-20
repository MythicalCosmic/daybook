"""groups.services.broadcast: other apps post to the company's groups without group internals."""

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.groups import services
from apps.groups.models import GroupEvent
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.tests.factories import PositionFactory
from apps.notifications import telegram

pytestmark = pytest.mark.django_db


@pytest.fixture
def posted(monkeypatch):
    """Group posts as (chat_id, text, photo, photo_storage)."""
    calls = []

    def record(bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"):
        calls.append((chat_id, text, photo, photo_storage))

    monkeypatch.setattr(telegram, "send_message", record)
    return calls


@pytest.fixture
def broadcast(django_capture_on_commit_callbacks):
    """services.broadcast, with the commit that queues the posts."""

    def run(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.broadcast(*args, **kwargs)

    return run


def chats(posted) -> set[int]:
    return {chat_id for chat_id, *_rest in posted}


@pytest.fixture
def sales_company(company):
    company.features = ["sales", "attendance"]
    company.save()
    return company


def test_every_group_that_wants_the_event_gets_it(sales_company, other_company, posted, broadcast):
    wants = TelegramGroupFactory(company=sales_company, events=[GroupEvent.SALES])
    also = TelegramGroupFactory(company=sales_company, events=[GroupEvent.SALES, GroupEvent.CASH])
    TelegramGroupFactory(company=sales_company, events=[GroupEvent.CASH])
    TelegramGroupFactory(company=sales_company, events=[GroupEvent.SALES], is_active=False)
    TelegramGroupFactory(company=other_company, events=[GroupEvent.SALES])

    count = broadcast(sales_company.pk, GroupEvent.SALES, "Sales today: 14 250 000 so'm")

    assert count == 2
    assert chats(posted) == {wants.chat_id, also.chat_id}
    assert {text for _chat, text, *_ in posted} == {"Sales today: 14 250 000 so'm"}


def test_a_switched_off_module_posts_nothing(company, posted, broadcast):
    TelegramGroupFactory(company=company, events=[GroupEvent.SALES])

    assert broadcast(company.pk, GroupEvent.SALES, "Sales") == 0
    assert posted == []


def test_task_events_need_no_module(company, posted, broadcast):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.LATE])

    assert broadcast(company.pk, GroupEvent.LATE, "Late") == 1
    assert chats(posted) == {group.chat_id}


def test_branch_news_reaches_that_branch_and_unfiltered_groups(sales_company, posted, broadcast):
    here = sales_company.branches.get()
    there = BranchFactory(company=sales_company)
    everywhere = TelegramGroupFactory(company=sales_company, events=[GroupEvent.SHIFTS])
    local = TelegramGroupFactory(company=sales_company, events=[GroupEvent.SHIFTS])
    local.branches.add(here)
    elsewhere = TelegramGroupFactory(company=sales_company, events=[GroupEvent.SHIFTS])
    elsewhere.branches.add(there)

    broadcast(sales_company.pk, GroupEvent.SHIFTS, "Shift closed", branch_id=here.pk)

    assert chats(posted) == {everywhere.chat_id, local.chat_id}


def test_position_news_reaches_matching_and_unfiltered_groups(sales_company, posted, broadcast):
    cashier = PositionFactory(company=sales_company)
    cook = PositionFactory(company=sales_company)
    everyone = TelegramGroupFactory(company=sales_company, events=[GroupEvent.ATTENDANCE])
    cashiers = TelegramGroupFactory(company=sales_company, events=[GroupEvent.ATTENDANCE])
    cashiers.positions.add(cashier)
    cooks = TelegramGroupFactory(company=sales_company, events=[GroupEvent.ATTENDANCE])
    cooks.positions.add(cook)

    broadcast(sales_company.pk, GroupEvent.ATTENDANCE, "Aziz is late", position_ids=[cashier.pk])

    assert chats(posted) == {everyone.chat_id, cashiers.chat_id}


def test_company_wide_news_reaches_every_group_that_wants_it(sales_company, posted, broadcast):
    narrowed = TelegramGroupFactory(company=sales_company, events=[GroupEvent.SALES])
    narrowed.positions.add(PositionFactory(company=sales_company))
    narrowed.branches.add(sales_company.branches.get())

    assert broadcast(sales_company.pk, GroupEvent.SALES, "Totals") == 1


def test_private_photos_travel_with_their_storage(sales_company, posted, broadcast):
    TelegramGroupFactory(company=sales_company, events=[GroupEvent.CASH])

    broadcast(
        sales_company.pk,
        GroupEvent.CASH,
        "Z-report",
        photo="zreports/1/a.jpg",
        photo_storage="private",
    )

    [(_chat, _text, photo, storage)] = posted
    assert (photo, storage) == ("zreports/1/a.jpg", "private")


def test_inactive_companies_and_unknown_storages(sales_company, posted, broadcast):
    TelegramGroupFactory(company=sales_company, events=[GroupEvent.SALES])
    with pytest.raises(ValueError):
        broadcast(sales_company.pk, GroupEvent.SALES, "x", photo_storage="s3")

    sales_company.is_active = False
    sales_company.save()
    assert broadcast(sales_company.pk, GroupEvent.SALES, "x") == 0


def test_posts_wait_for_the_callers_commit(
    sales_company, posted, django_capture_on_commit_callbacks
):
    TelegramGroupFactory(company=sales_company, events=[GroupEvent.SALES])

    with django_capture_on_commit_callbacks(execute=False) as queued:
        assert services.broadcast(sales_company.pk, GroupEvent.SALES, "Totals") == 1

    assert posted == []  # a change rolled back after this would have reached no group
    assert len(queued) == 1
