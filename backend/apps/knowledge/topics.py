"""Topics: the subjects pages, lessons and questions are about (docs/PLAN-LEARNING.md §3.1).

Shared by the knowledge base and learning, so both kinds of managers keep them: holders of
`knowledge.manage` or `learning.manage`. Archived topics stay on what they tag (history, the
skill matrix) but are offered for nothing new.

    topic = topics.create_topic(company, by=manager, name="Sovuq zanjir", color="sky")
    topics.add_pharmacy_topics(company, by=manager)     # the usual ones, in the company's language
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, QuerySet
from django.db.models.functions import Lower
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.knowledge.audit_actions import KnowledgeAction
from apps.knowledge.models import Topic
from apps.members.models import Membership
from apps.members.permissions import Perm

PULSE_KEY = "knowledge.topics"
MAX_NAME = 80
# Palette keys the dashboard and the mini app turn into colours.
COLORS = (
    "gray",
    "red",
    "orange",
    "amber",
    "green",
    "teal",
    "sky",
    "blue",
    "indigo",
    "violet",
    "pink",
)
# What pharmacy staff learn and are checked on (docs/research/pharmacy.md), one click away.
PHARMACY_TOPICS = (
    (gettext_lazy("Cold chain"), "sky"),
    (gettext_lazy("Prescription medicines"), "violet"),
    (gettext_lazy("Controlled substances"), "red"),
    (gettext_lazy("Storage and expiry dates"), "teal"),
    (gettext_lazy("Goods receipt"), "orange"),
    (gettext_lazy("Prices and the till"), "amber"),
    (gettext_lazy("Analogues and advice"), "indigo"),
    (gettext_lazy("Customer service"), "pink"),
    (gettext_lazy("Hygiene and sanitary rules"), "green"),
)


def can_manage(member: Membership | None) -> bool:
    return (
        member is None
        or member.has_perm(Perm.KNOWLEDGE_MANAGE)
        or member.has_perm(Perm.LEARNING_MANAGE)
    )


def _ensure_manager(by: Membership | None) -> None:
    if not can_manage(by):
        raise PermissionDenied(
            _("Only people who manage the knowledge base or training can do this.")
        )


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise DomainError(_("Give the topic a name."))
    if len(name) > MAX_NAME:
        raise DomainError(_("Keep the name under %(n)d characters.") % {"n": MAX_NAME})
    return name


def _clean_color(color: str) -> str:
    color = (color or "").strip()
    if color and color not in COLORS:
        raise DomainError(_("Pick one of the colours."))
    return color


def _taken(company_id: int, name: str, *, exclude: int | None = None) -> bool:
    rows = Topic.objects.filter(company_id=company_id, archived_at__isnull=True).annotate(
        lower=Lower("name")
    )
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    return rows.filter(lower=name.lower()).exists()


def _record(action: str, topic: Topic, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=topic.company_id,
        actor=by.user if by is not None else None,
        target=topic,
        **details,
    )
    transaction.on_commit(lambda: pulse.bump(topic.company_id, PULSE_KEY))


# Reading --------------------------------------------------------------------------------


def topics(company, *, include_archived: bool = False) -> QuerySet[Topic]:
    """The company's topics in their order, each with `page_count`, `lesson_count` and
    `question_count` (live ones only)."""
    rows = Topic.objects.filter(company=company)
    if not include_archived:
        rows = rows.filter(archived_at__isnull=True)
    return rows.annotate(
        page_count=Count("pages", filter=Q(pages__archived_at__isnull=True), distinct=True),
        lesson_count=Count("lessons", filter=Q(lessons__archived_at__isnull=True), distinct=True),
        question_count=Count("questions", filter=~Q(questions__state="archived"), distinct=True),
    ).order_by("position", "pk")


def live_ids(company_id: int, ids) -> list[int]:
    """`ids` that are live topics of the company, in the order given; anything else is refused
    (for the pickers of pages, lessons and questions)."""
    wanted = [int(pk) for pk in ids or ()]
    found = set(
        Topic.objects.filter(
            company_id=company_id, pk__in=wanted, archived_at__isnull=True
        ).values_list("pk", flat=True)
    )
    if len(found) != len(set(wanted)):
        raise DomainError(_("Pick topics of this company."))
    return list(dict.fromkeys(wanted))


# Writing --------------------------------------------------------------------------------


@transaction.atomic
def create_topic(
    company, *, by: Membership | None, name: str, color: str = "", description: str = ""
) -> Topic:
    _ensure_manager(by)
    name = _clean_name(name)
    if _taken(company.pk, name):
        raise DomainError(_("There is already a topic with this name."))
    last = Topic.objects.filter(company=company).aggregate(top=Max("position"))["top"]
    try:
        with transaction.atomic():
            topic = Topic.objects.create(
                company=company,
                name=name,
                color=_clean_color(color),
                description=(description or "").strip()[:300],
                position=(last or 0) + 1,
                created_by=by,
            )
    except IntegrityError:  # the same name at the same moment
        raise DomainError(_("There is already a topic with this name.")) from None
    _record(KnowledgeAction.TOPIC_CREATED, topic, by, name=name)
    return topic


@transaction.atomic
def update_topic(topic: Topic, *, by: Membership | None, **changes) -> Topic:
    """Change `name`, `color` and `description`."""
    _ensure_manager(by)
    unknown = set(changes) - {"name", "color", "description"}
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} on a topic.")
    topic = Topic.objects.select_for_update().get(pk=topic.pk)
    if "name" in changes:
        name = _clean_name(changes["name"])
        if topic.archived_at is None and _taken(topic.company_id, name, exclude=topic.pk):
            raise DomainError(_("There is already a topic with this name."))
        topic.name = name
    if "color" in changes:
        topic.color = _clean_color(changes["color"])
    if "description" in changes:
        topic.description = (changes["description"] or "").strip()[:300]
    topic.save()
    _record(KnowledgeAction.TOPIC_CHANGED, topic, by, changed=sorted(changes))
    return topic


@transaction.atomic
def archive_topic(topic: Topic, *, by: Membership | None) -> Topic:
    _ensure_manager(by)
    topic = Topic.objects.select_for_update().get(pk=topic.pk)
    if topic.archived_at is None:
        topic.archived_at = timezone.now()
        topic.save(update_fields=["archived_at", "updated_at"])
        _record(KnowledgeAction.TOPIC_ARCHIVED, topic, by)
    return topic


@transaction.atomic
def restore_topic(topic: Topic, *, by: Membership | None) -> Topic:
    _ensure_manager(by)
    topic = Topic.objects.select_for_update().get(pk=topic.pk)
    if topic.archived_at is not None:
        if _taken(topic.company_id, topic.name, exclude=topic.pk):
            raise DomainError(_("There is already a topic with this name."))
        topic.archived_at = None
        topic.save(update_fields=["archived_at", "updated_at"])
        _record(KnowledgeAction.TOPIC_CHANGED, topic, by, changed=["archived_at"])
    return topic


@transaction.atomic
def reorder_topics(company, ids: list[int], *, by: Membership | None) -> None:
    _ensure_manager(by)
    rows = {row.pk: row for row in Topic.objects.filter(company=company, pk__in=ids)}
    for index, pk in enumerate(ids):
        topic = rows.get(int(pk))
        if topic is not None and topic.position != index:
            topic.position = index
            topic.save(update_fields=["position", "updated_at"])
    if rows:
        transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_KEY))


@transaction.atomic
def add_pharmacy_topics(company, *, by: Membership | None) -> list[Topic]:
    """The usual pharmacy topics the company doesn't have yet, named in its language."""
    _ensure_manager(by)
    made = []
    with translation.override(company.default_language):
        for name, color in PHARMACY_TOPICS:
            if not _taken(company.pk, str(name)):
                made.append(create_topic(company, by=by, name=str(name), color=color))
    return made
