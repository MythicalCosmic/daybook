"""The AI features' JSON, the same on the employee and the owner API (v0.2 AI contract §4, §5).

`AIDraftSerializer` renders an AIDraft exactly as the contract shows it; the declared fields
describe the shape for the OpenAPI schemas, and `present()` builds it. What depends on the
clock or on rights (due_text, no_due, past_due, not_allowed) is worked out here, at read time,
in the reader's language and the company's timezone.
"""

from zoneinfo import ZoneInfo

from django.utils import timezone, translation
from rest_framework import serializers

from apps.ai import bot_messages, drafting
from apps.ai.drafts import allowed_ids, moment
from apps.ai.models import AIDraft
from apps.core.files import signed_url
from apps.core.models import Language
from apps.members.models import Membership
from apps.tasks import dates
from apps.tasks.models import Task

PROBLEMS = ("no_assignee_match", "ambiguous_assignee", "no_due", "past_due", "not_allowed")
ERROR_CODES = (
    "speech_unavailable",
    "audio_unreadable",
    "nothing_heard",
    "ai_unavailable",
    "expired",
)
AUDIO_TTL = 60 * 60


class AIPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class AIAssigneeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField(allow_blank=True)


class AIAudioSerializer(serializers.Serializer):
    seconds = serializers.IntegerField(allow_null=True)
    url = serializers.CharField(allow_null=True, help_text="Signed link to the recording.")


class AIDraftItemSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    assignee = AIAssigneeSerializer(allow_null=True, help_text="null: for the author.")
    assignee_guess = serializers.CharField(
        allow_blank=True, help_text="Who was heard but not matched, when assignee is null."
    )
    due_at = serializers.DateTimeField(allow_null=True)
    due_text = serializers.CharField(allow_blank=True, help_text="Ertaga, 10:00")
    priority = serializers.ChoiceField(["normal", "urgent"])
    checklist = serializers.ListField(child=serializers.CharField())
    proof = serializers.ChoiceField(["none", "photo"])
    problems = serializers.ListField(child=serializers.ChoiceField(PROBLEMS))


class AICreatedTaskSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    assignee_name = serializers.CharField()


class AIDraftSerializer(serializers.Serializer):
    """One voice note or typed instruction and the tasks it became."""

    id = serializers.IntegerField()
    status = serializers.ChoiceField(AIDraft.Status.choices)
    source = serializers.ChoiceField(AIDraft.Source.choices)
    author = AIPersonSerializer()
    created_at = serializers.DateTimeField()
    audio = AIAudioSerializer(allow_null=True, help_text="null for typed text.")
    transcript = serializers.CharField(allow_blank=True)
    language = serializers.CharField(allow_blank=True)
    engine = serializers.CharField(allow_blank=True, help_text="claude, rules or fake.")
    drafts = AIDraftItemSerializer(many=True)
    questions = serializers.ListField(child=serializers.CharField())
    created_tasks = AICreatedTaskSerializer(many=True)
    error_code = serializers.CharField(
        allow_blank=True, help_text=f"Empty, or one of: {', '.join(ERROR_CODES)}."
    )
    error = serializers.CharField(allow_blank=True, help_text="error_code in words.")

    def to_representation(self, instance: AIDraft) -> dict:
        request = self.context.get("request")
        return present(instance, user=getattr(request, "user", None))


def present(draft: AIDraft, *, user=None) -> dict:
    """The contract's AIDraft JSON for `draft`, as `user` (for the audio link) reads it."""
    company = draft.company
    now = timezone.localtime(timezone.now(), ZoneInfo(company.timezone))
    lang = dates.language(translation.get_language())
    items = draft.drafts
    ids = {item.get("assignee_id") for item in items if item.get("assignee_id")}
    people = (
        {
            person.pk: person
            for person in Membership.objects.for_company(company)
            .filter(pk__in=ids)
            .select_related("user", "position")
        }
        if ids
        else {}
    )
    allowed = allowed_ids(draft.created_by) if ids and draft.status == AIDraft.Status.READY else ids
    audio = None
    if draft.audio or draft.audio_seconds:
        url = None
        if draft.audio and user is not None and user.is_authenticated:
            url = signed_url(
                draft.audio,
                user=user,
                company_id=draft.company_id,
                check=f"ai.draft:{draft.pk}",
                ttl=AUDIO_TTL,
            )
        audio = {"seconds": draft.audio_seconds, "url": url}
    return {
        "id": draft.pk,
        "status": draft.status,
        "source": draft.source,
        "author": {"id": draft.created_by_id, "name": str(draft.created_by)},
        "created_at": timezone.localtime(draft.created_at, now.tzinfo).isoformat(),
        "audio": audio,
        "transcript": draft.transcript,
        "language": draft.language,
        "engine": draft.engine,
        "drafts": [_item(item, people, allowed, now, lang) for item in items],
        "questions": draft.questions,
        "created_tasks": _created(draft),
        "error_code": draft.error_code,
        "error": bot_messages.error_text(draft.error_code),
    }


def _item(item: dict, people: dict, allowed: set, now, lang: str) -> dict:
    person = people.get(item.get("assignee_id"))
    due = moment(item.get("due_at"))
    problems = [p for p in item.get("problems") or [] if p in PROBLEMS]
    if item.get("assignee_id") and person is None:
        problems.append("not_allowed")  # gone from the company, or another company's id
    elif person is not None and person.pk not in allowed:
        problems.append("not_allowed")
    due_text = ""
    if due is None:
        problems.append("no_due")
    else:
        local = timezone.localtime(due, now.tzinfo)
        due_text = dates.short_due(local, now, lang)
        due_text = due_text[0].upper() + due_text[1:]
        if due <= now:
            problems.append("past_due")
    return {
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "assignee": (
            {
                "id": person.pk,
                "name": str(person),
                "position": person.position.name if person.position_id else "",
            }
            if person
            else None
        ),
        "assignee_guess": item.get("assignee_guess", "") if person is None else "",
        "due_at": timezone.localtime(due, now.tzinfo).isoformat() if due else None,
        "due_text": due_text,
        "priority": item.get("priority", "normal"),
        "checklist": list(item.get("checklist") or []),
        "proof": item.get("proof", "none"),
        "problems": list(dict.fromkeys(problems)),
    }


def _created(draft: AIDraft) -> list[dict]:
    if not draft.applied_ids:
        return []
    tasks = {
        task.pk: task
        for task in Task.objects.filter(
            company_id=draft.company_id, pk__in=draft.applied_ids
        ).select_related("assignee__user")
    }
    return [
        {"id": task.pk, "title": task.title, "assignee_name": str(task.assignee)}
        for pk in draft.applied_ids
        if (task := tasks.get(pk)) is not None
    ]


# Writing ----------------------------------------------------------------------------------------


class AIDraftCreateSerializer(serializers.Serializer):
    """Multipart `audio` (+ `seconds`, `language`) or JSON `text`."""

    audio = serializers.FileField(required=False)
    seconds = serializers.FloatField(required=False, min_value=0, allow_null=True)
    language = serializers.ChoiceField(Language.choices, required=False, allow_null=True)
    text = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False, help_text="1–2000 characters."
    )

    def validate(self, attrs):
        if bool(attrs.get("audio")) == (attrs.get("text") is not None):
            raise serializers.ValidationError("Send either audio or text.")
        return attrs


class AIDraftEditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=drafting.TITLE_MAX)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=drafting.DESCRIPTION_MAX
    )
    assignee_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    due_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    priority = serializers.ChoiceField(["normal", "urgent"], required=False, default="normal")
    checklist = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        default=list,
        max_length=drafting.MAX_CHECKLIST,
    )
    proof = serializers.ChoiceField(["none", "photo"], required=False, default="none")


class AIDraftApplySerializer(serializers.Serializer):
    drafts = AIDraftEditSerializer(
        many=True, required=False, max_length=drafting.MAX_DRAFTS, allow_empty=False
    )


class AIApplyFailureSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    detail = serializers.CharField()


class AIApplyResultSerializer(serializers.Serializer):
    draft = AIDraftSerializer()
    created = serializers.ListField(child=serializers.IntegerField())
    failed = AIApplyFailureSerializer(many=True)


class AIErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class AIVoiceStatusSerializer(serializers.Serializer):
    voice = serializers.BooleanField(help_text="Recording is offered.")
    smart_text = serializers.BooleanField(help_text="Typed instructions are offered.")
    engine = serializers.ChoiceField(["claude", "rules"])
    max_seconds = serializers.IntegerField()
    auto_create = serializers.BooleanField()
    bot_username = serializers.CharField(allow_blank=True)
