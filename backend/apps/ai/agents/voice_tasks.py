"""Voice tasks: voice messages and typed instructions become task drafts, and tasks.

Not scheduled: it works whenever someone sends a voice message to a bot or dictates in an app
(apps.ai.drafts). With `auto_create` the tasks are created at once when every draft names a
person the author may give work to and a time to come; the bot card then offers Undo.
"""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext_lazy

from apps.ai.agents.registry import Agent, EventTemplate, Field, register

KEY = "voice_tasks"
# How long "Undo" stays on the card after an automatic create.
UNDO_MINUTES = 10


def _schedule(config: dict) -> str:
    if config.get("auto_create"):
        return _("When someone dictates; creates the tasks at once")
    return _("When someone dictates")


AGENT = register(
    Agent(
        key=KEY,
        order=10,
        name=gettext_lazy("Voice tasks"),
        description=gettext_lazy(
            "Turns voice messages and typed instructions into tasks: who it is for, by when, "
            "urgent or not, photo or not."
        ),
        icon="mic",
        needs_claude=False,
        default_enabled=True,
        needs_speech=True,
        fields=(
            Field(
                "auto_create",
                "bool",
                gettext_lazy("Create at once"),
                False,
                help=gettext_lazy(
                    "Create the tasks without asking when everyone is known and every time is "
                    "clear. The message keeps an Undo button for 10 minutes."
                ),
            ),
            Field(
                "max_seconds",
                "int",
                gettext_lazy("Longest voice message"),
                120,
                min=15,
                max=300,
                unit=gettext_lazy("seconds"),
            ),
        ),
        schedule=_schedule,
        events={
            "draft_ready": EventTemplate(
                ngettext_lazy(
                    "Understood %(count)s task from %(author)s",
                    "Understood %(count)s tasks from %(author)s",
                    "count",
                )
            ),
            "draft_applied": EventTemplate(
                ngettext_lazy(
                    "%(actor)s created %(count)s task from a voice note",
                    "%(actor)s created %(count)s tasks from a voice note",
                    "count",
                ),
                level="success",
            ),
            "draft_auto_applied": EventTemplate(
                ngettext_lazy(
                    "Created %(count)s task at once from a voice note by %(author)s",
                    "Created %(count)s tasks at once from a voice note by %(author)s",
                    "count",
                ),
                level="success",
            ),
            "draft_failed": EventTemplate(
                gettext_lazy("Could not understand a voice note from %(author)s"),
                level="warning",
            ),
            "draft_undone": EventTemplate(
                gettext_lazy("%(actor)s took back the tasks of a voice note")
            ),
        },
    )
)
