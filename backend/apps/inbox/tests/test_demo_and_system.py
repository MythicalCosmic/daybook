"""The inbox's own kind (messages from the product) and its demo data."""

import pytest
from django.utils import timezone

from apps.inbox import demo, queries
from apps.inbox.models import Notification
from apps.inbox.services import run_action

pytestmark = pytest.mark.django_db


def test_demo_gives_the_owner_and_manager_messages(company, demo_people):
    people = demo_people(company)

    demo.seed(company, people, timezone.now())

    owner_inbox = list(queries.inbox(people["owner"]))
    assert len(owner_inbox) == 3
    assert queries.unread_count(people["owner"]) == 2
    assert {n.title for n in queries.inbox(people["manager"])} == {
        "Welcome to your dashboard",
        "Next week's roster isn't published yet",
    }
    assert not Notification.objects.filter(recipient=people["worker"]).exists()


def test_demo_messages_are_in_each_readers_language(company, demo_people):
    people = demo_people(company)
    for key, language in (("owner", "uz"), ("manager", "ru")):
        people[key].user.language = language
        people[key].user.save(update_fields=["language"])

    demo.seed(company, people, timezone.now())

    welcome = Notification.objects.filter(dedupe_key="demo:welcome")
    uzbek = welcome.get(recipient=people["owner"])
    assert uzbek.title == "Boshqaruv paneliga xush kelibsiz"
    assert uzbek.actions[0]["label"] == "Tushunarli"
    assert welcome.get(recipient=people["manager"]).title == "Добро пожаловать в панель управления"


def test_demo_can_run_twice(company, demo_people):
    people = demo_people(company)

    demo.seed(company, people, timezone.now())
    demo.seed(company, people, timezone.now())

    assert Notification.objects.filter(recipient=people["owner"]).count() == 3


def test_got_it_settles_a_message(company, demo_people):
    people = demo_people(company)
    demo.seed(company, people, timezone.now())
    welcome = Notification.objects.get(recipient=people["owner"], dedupe_key="demo:welcome")

    assert run_action(welcome.pk, "got_it", by=people["owner"]) is None

    welcome.refresh_from_db()
    assert welcome.acted_at is not None and welcome.read_at is not None
