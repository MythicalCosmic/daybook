import pytest

from apps.groups import bot_messages
from apps.groups.models import GroupEvent, available_events
from apps.groups.tests.factories import TelegramGroupFactory

pytestmark = pytest.mark.django_db

TASK_EVENTS = [
    GroupEvent.DAILY_DONE,
    GroupEvent.TASKS_DONE,
    GroupEvent.LATE,
    GroupEvent.MEMBERS,
    GroupEvent.MORNING,
    GroupEvent.EVENING,
]


def toggles(group) -> list[str]:
    _, markup = bot_messages.settings(group)
    return [row[0].text for row in markup.inline_keyboard[:-2]]


def test_module_events_wait_for_their_module(company):
    assert available_events(company) == TASK_EVENTS

    company.features = ["sales", "recognition"]

    assert available_events(company) == [
        *TASK_EVENTS,
        GroupEvent.CASH,
        GroupEvent.SALES,
        GroupEvent.KUDOS,
    ]


def test_a_chosen_event_stays_listed_after_its_module_is_switched_off(company):
    assert GroupEvent.ATTENDANCE in available_events(company, [GroupEvent.ATTENDANCE])


def test_the_bot_offers_only_the_available_events(company):
    group = TelegramGroupFactory(company=company)

    assert len(toggles(group)) == len(TASK_EVENTS)

    company.features = ["attendance"]
    company.save()
    group.refresh_from_db()
    labels = toggles(group)
    assert len(labels) == len(TASK_EVENTS) + 2
    assert labels[-2].endswith(str(GroupEvent.ATTENDANCE.label))
    assert labels[-1].endswith(str(GroupEvent.SHIFTS.label))
