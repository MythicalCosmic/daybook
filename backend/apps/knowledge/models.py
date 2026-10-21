"""Models of the knowledge base (docs/PLAN-OWNER.md §13.5).

A company keeps its how-tos in **spaces** ("Kassa", "Yangi xodimlar uchun"), each read by
everyone or by some positions. A space holds a tree of **pages**. A page's body is HTML from the
dashboard editor, cleaned against an allow-list before it is stored (`sanitize.py`), with a
plain-text copy for search and for the bot.

Every save that changes a page's content writes a **version**. People confirm they have read a
page with an **acknowledgement** of the version they saw; `ack_version` is the version from
which an acknowledgement counts (publishing with "ask everyone to read it again" moves it).

Pages can be linked to a task or a routine ("How to do this"). Pictures in pages live in private
storage and are shown through short signed links made for each reader.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership, Position


class Space(TenantModel):
    """A shelf of pages, read by everyone or by the positions in `positions`."""

    name = models.CharField(max_length=100)
    icon = models.CharField(
        max_length=16, blank=True, help_text=_("An emoji shown next to the name.")
    )
    description = models.CharField(max_length=300, blank=True)
    audience_all = models.BooleanField(
        default=True, help_text=_("Everyone in the company reads it. Otherwise only `positions`.")
    )
    positions = models.ManyToManyField(Position, blank=True, related_name="knowledge_spaces")
    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["company", "archived_at", "position"])]

    def __str__(self):
        return self.name


class Page(TenantModel):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="pages")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=16, blank=True)
    body = models.TextField(blank=True, help_text=_("Sanitized HTML from the dashboard editor."))
    body_text = models.TextField(blank=True, help_text=_("Plain text of the body, for search."))
    position = models.PositiveIntegerField(default=0)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    require_ack = models.BooleanField(
        default=False, help_text=_("Everyone who reads it confirms they have read it.")
    )
    version = models.PositiveIntegerField(default=1)
    ack_version = models.PositiveIntegerField(
        default=1, help_text=_("Acknowledgements of this version or later count as read.")
    )
    ack_since = models.DateTimeField(
        null=True, blank=True, help_text=_("When readers were asked to read `ack_version`.")
    )
    reminded_version = models.PositiveIntegerField(
        default=0, help_text=_("The ack version the unread reminder was last sent for.")
    )
    updated_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "pk"]
        indexes = [
            models.Index(fields=["company", "space", "parent", "position"]),
            models.Index(fields=["company", "published", "archived_at"]),
        ]

    def __str__(self):
        return self.title


class PageVersion(TenantModel):
    """The page as it was after one save. Restoring a version saves it again as the newest."""

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=16, blank=True)
    body = models.TextField(blank=True)
    note = models.CharField(max_length=200, blank=True, help_text=_("What changed."))
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["page", "version"], name="knowledge_unique_version")
        ]


class PageAck(TenantModel):
    """`membership` confirmed reading `version` of `page` at `at`."""

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="acks")
    version = models.PositiveIntegerField()
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="knowledge_acks"
    )
    at = models.DateTimeField()

    class Meta:
        ordering = ["-at"]
        constraints = [
            models.UniqueConstraint(
                fields=["page", "membership", "version"], name="knowledge_unique_ack"
            )
        ]
        indexes = [models.Index(fields=["membership", "page", "version"])]


class PageLink(TenantModel):
    """A page linked to a task or a routine: "How to do this"."""

    class Target(models.TextChoices):
        TASK = "task", _("Task")
        ROUTINE = "routine", _("Routine")

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="links")
    target_type = models.CharField(max_length=8, choices=Target.choices)
    target_id = models.PositiveBigIntegerField()
    target_title = models.CharField(
        max_length=200, blank=True, help_text=_("The task's or routine's title when linked.")
    )
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["page", "target_type", "target_id"], name="knowledge_unique_link"
            )
        ]
        indexes = [models.Index(fields=["company", "target_type", "target_id"])]


class PageImage(TenantModel):
    """A picture in a page, re-encoded on upload and kept in private storage."""

    page = models.ForeignKey(
        Page, on_delete=models.SET_NULL, null=True, blank=True, related_name="images"
    )
    file = models.FileField(storage=private_storage, upload_to=private_upload_to("knowledge"))
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )


class KnowledgeSettings(models.Model):
    """The company's knowledge base settings (`conf.get_settings`)."""

    company = models.OneToOneField(
        "companies.Company", on_delete=models.CASCADE, related_name="knowledge_settings"
    )
    notify_on_publish = models.BooleanField(
        default=True, help_text=_("Tell the readers in Telegram when a page is published.")
    )
    remind_unread_after_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text=_("Remind people who haven't confirmed a page after this many hours (0: never)."),
    )

    def __str__(self):
        return f"Knowledge settings of {self.company_id}"


# Published, not archived: the pages readers can open.
LIVE = Q(published=True, archived_at__isnull=True)
