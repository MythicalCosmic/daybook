"""Ko‘z alerts in the owner bot: a manager presses "I'll go" under an alert."""

import pytest
from asgiref.sync import sync_to_async

from apps.vision.callbacks import KozButton
from apps.vision.models import Alert
from apps.vision.tests import factories
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def alert_for(company, person) -> Alert:
    company.features = [*company.features, "vision"]
    company.save(update_fields=["features"])
    branch = company.branches.order_by("pk").first()
    alert = factories.make_alert(factories.make_camera(factories.make_box(branch)))
    factories.copy_to(alert, person, reason="manager", bot="owner")
    return alert


async def test_a_manager_goes_from_the_owner_bot(dp, bot, company, member):
    owner = await member.acreate(company, "Owner")
    alert = await alert_for(company, owner)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(owner.user.telegram_id), KozButton(alert_id=alert.pk).pack()
        ),
    )

    [answer] = bot.answers()
    assert (answer.text, answer.show_alert) == ("Thank you: everyone sees you're going.", False)
    await alert.arefresh_from_db()
    assert alert.acknowledged_by_id == owner.pk


async def test_an_alert_that_ended_needs_nobody(dp, bot, company, member):
    owner = await member.acreate(company, "Owner")
    alert = await alert_for(company, owner)
    await Alert.objects.filter(pk=alert.pk).aupdate(state=Alert.State.RESOLVED)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(owner.user.telegram_id), KozButton(alert_id=alert.pk).pack()
        ),
    )

    [answer] = bot.answers()
    assert (answer.text, answer.show_alert) == ("It's over already: nobody needs to go.", True)
