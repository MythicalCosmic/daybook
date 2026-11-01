"""People type `<`, `>` and `&` into names, task titles, steps, comments and reasons ("Harorat
< 8 °C"). The bot writes HTML, so each of them must reach Telegram escaped, or Telegram refuses
the whole message. The `bot` fixture fails a test on any message Telegram would refuse
(apps.notifications.tests.telegram_checks); these walk the screens with such texts everywhere."""

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.companies.models import Branch
from apps.members import departments
from apps.tasks.callbacks import TaskAction, TaskCallback, TeamCallback
from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment
from apps.tasks.tests.factories import jpeg_bytes
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

HOSTILE = "<Ali> & <b>Vali</b>"
TITLE = "Harorat < 8 °C & <i>muzlatgich</i>"


def press(action: TaskAction, task_id: int = 0) -> str:
    return TaskCallback(action=action, task_id=task_id).pack()


@pytest.fixture
def team(company, member):
    def setup():
        company.name = "Dori & <Shifo>"
        company.save(update_fields=["name"])
        Branch.objects.filter(company=company).update(name="Chilonzor <1> & 2")
        owner = member.registered(company, "Owner", first_name="Ega", last_name="<Bosh>")
        head = member.registered(company, "Manager", first_name="Bek <zod>", last_name="&")
        worker = member.registered(company, first_name=HOSTILE, last_name="<o‘g‘li>")
        unit = departments.create_department(company, by=owner, name="Savdo & <Kassa>", head=head)
        departments.place(unit, by=owner, people=[head, worker])
        now = timezone.now()
        open_task = Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title=TITLE,
            description="Tekshiring: <3 & >8 bo‘lsa xabar bering",
            assignee=worker,
            created_by=head,
            branch=worker.home_branch,
            due_at=now + timedelta(hours=2),
            blocker_note="<yo‘q>",
        )
        ChecklistItem.objects.create(task=open_task, text="Qadam <1> & 2", order=0)
        TaskComment.objects.create(task=open_task, author=head, text="Iltimos <tez> & aniq")
        done = Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title=TITLE + " (bajarildi)",
            assignee=worker,
            created_by=head,
            status=Task.Status.DONE,
            proof=Proof.PHOTO,
            proof_text="Hammasi <joyida> & toza",
            completed_at=now,
        )
        done.proof_photo.save("proof.jpg", ContentFile(jpeg_bytes()))
        review = Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title=TITLE + " (tekshiruvda)",
            assignee=worker,
            created_by=head,
            status=Task.Status.REVIEW,
            needs_confirmation=True,
            proof_text="<rasm> & hisobot",
            completed_at=now,
        )
        return {
            "head": head,
            "worker": worker,
            "open": open_task,
            "done": done,
            "review": review,
        }

    return sync_to_async(setup)()


async def test_the_worker_screens_escape_every_text(dp, bot, team):
    people = await team
    worker = updates.tg_user(people["worker"].user.telegram_id)

    await dp.feed_update(bot, updates.message(worker, "/start"))
    await dp.feed_update(bot, updates.message(worker, "My tasks"))
    await dp.feed_update(bot, updates.callback(worker, press(TaskAction.OPEN, people["open"].pk)))
    await dp.feed_update(bot, updates.callback(worker, press(TaskAction.START, people["open"].pk)))
    await dp.feed_update(bot, updates.callback(worker, press(TaskAction.BLOCK, people["open"].pk)))
    await dp.feed_update(bot, updates.callback(worker, press(TaskAction.OPEN, people["done"].pk)))

    assert bot.requests  # every message above went through the Telegram checks


async def test_a_new_task_with_angle_brackets_and_ampersands(dp, bot, team):
    people = await team
    worker = updates.tg_user(people["worker"].user.telegram_id)

    await dp.feed_update(bot, updates.message(worker, "New task"))
    await dp.feed_update(bot, updates.message(worker, "Vitrina <2> & kassa"))

    assert bot.requests


async def test_the_heads_screens_escape_every_text(dp, bot, team):
    people = await team
    head = updates.tg_user(people["head"].user.telegram_id)

    await dp.feed_update(bot, updates.message(head, "My team"))
    await dp.feed_update(
        bot, updates.callback(head, TeamCallback(member_id=people["worker"].pk).pack())
    )
    await dp.feed_update(bot, updates.callback(head, press(TaskAction.PHOTO, people["done"].pk)))
    await dp.feed_update(bot, updates.message(head, "To check"))
    await dp.feed_update(bot, updates.callback(head, press(TaskAction.OPEN, people["review"].pk)))
    await dp.feed_update(bot, updates.callback(head, press(TaskAction.RETURN, people["review"].pk)))
    await dp.feed_update(bot, updates.message(head, "Rasm <xira> & qayta"))

    assert bot.requests
