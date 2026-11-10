"""Shapes of the hiring endpoints (`hr/vacancies/`, `hr/applicants/`). Money leaves as strings,
dates as `YYYY-MM-DD`; an applicant's Telegram id never leaves (their @username does, to write
to them)."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import PrivateFileSerializerField
from apps.core.money import MoneySerializerField
from apps.hr.hiring import queries, services
from apps.hr.hiring.questions import MAX_OPTIONS, MAX_QUESTIONS, OPTION_MAX, TEXT_MAX
from apps.hr.models import Applicant, ApplicantEvent, QuestionKind, Vacancy
from apps.hr.serializers import BranchRefSerializer, NamedSerializer, PersonRefSerializer
from apps.members import services as members
from apps.members.queries import branch_ref, person_ref


def _named(row) -> dict | None:
    return {"id": row.pk, "name": row.name} if row is not None else None


class QuestionSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, max_length=16)
    text = serializers.CharField(max_length=TEXT_MAX)
    kind = serializers.ChoiceField(choices=QuestionKind.choices, default=QuestionKind.TEXT)
    required = serializers.BooleanField(default=True)
    options = serializers.ListField(
        child=serializers.CharField(max_length=OPTION_MAX),
        max_length=MAX_OPTIONS,
        required=False,
        default=list,
        help_text="The buttons of a choice question (2 to 6).",
    )

    class Meta:
        ref_name = "HrVacancyQuestion"


class StageCountsSerializer(serializers.Serializer):
    new = serializers.IntegerField()
    screening = serializers.IntegerField()
    interview = serializers.IntegerField()
    offer = serializers.IntegerField()
    hired = serializers.IntegerField()
    rejected = serializers.IntegerField()
    total = serializers.IntegerField()

    class Meta:
        ref_name = "HrApplicantStageCounts"


class VacancySerializer(serializers.ModelSerializer):
    position = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField(
        help_text="The access a person hired for it gets: the position's role, else the default."
    )
    branch = serializers.SerializerMethodField()
    salary_from = MoneySerializerField(positive=False, allow_null=True, read_only=True)
    salary_to = MoneySerializerField(positive=False, allow_null=True, read_only=True)
    currency = serializers.SerializerMethodField()
    questions = QuestionSerializer(many=True, read_only=True)
    accepting = serializers.SerializerMethodField(help_text="The link takes applications today.")
    link = serializers.SerializerMethodField(help_text='"" until the bot username is set.')
    qr_link = serializers.SerializerMethodField(
        help_text="The link the QR code carries (its applicants count apart)."
    )
    counts = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    hire_blocker = serializers.SerializerMethodField(
        help_text="Why the viewer can't hire for it (null: they can)."
    )

    class Meta:
        model = Vacancy
        fields = (
            "id",
            "title",
            "status",
            "accepting",
            "position",
            "role",
            "branch",
            "description",
            "salary_from",
            "salary_to",
            "currency",
            "questions",
            "asks_document",
            "opens_on",
            "closes_on",
            "link",
            "qr_link",
            "link_opens",
            "counts",
            "created_by",
            "created_at",
            "published_at",
            "closed_at",
            "hire_blocker",
        )
        read_only_fields = fields
        ref_name = "HrVacancy"

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, vacancy: Vacancy) -> dict | None:
        return _named(vacancy.position)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_role(self, vacancy: Vacancy) -> dict | None:
        if vacancy.position is None:
            return None
        return _named(members.title_role(vacancy.position, vacancy.company))

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_branch(self, vacancy: Vacancy) -> dict | None:
        return branch_ref(vacancy.branch)

    def get_currency(self, vacancy: Vacancy) -> str:
        return vacancy.company.base_currency

    def get_accepting(self, vacancy: Vacancy) -> bool:
        return services.accepting(vacancy)

    def get_link(self, vacancy: Vacancy) -> str:
        return vacancy.bot_link()

    def get_qr_link(self, vacancy: Vacancy) -> str:
        return vacancy.bot_link(qr=True)

    @extend_schema_field(StageCountsSerializer)
    def get_counts(self, vacancy: Vacancy) -> dict:
        if hasattr(vacancy, "count_total"):
            counts = {stage: getattr(vacancy, f"count_{stage}") for stage in queries.STAGES}
        else:
            counts = queries.stage_counts(vacancy.applicants.all())
        return {**counts, "total": sum(counts.values())}

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_created_by(self, vacancy: Vacancy) -> dict | None:
        return person_ref(vacancy.created_by)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_hire_blocker(self, vacancy: Vacancy) -> str | None:
        viewer = self.context.get("membership")
        return services.hire_blocker(viewer, vacancy) if viewer is not None else None


class VacancyWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=services.TITLE_MAX)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    branch_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Empty: any branch (needs every branch)."
    )
    description = serializers.CharField(
        max_length=services.DESCRIPTION_MAX, required=False, allow_blank=True
    )
    salary_from = MoneySerializerField(positive=False, required=False, allow_null=True)
    salary_to = MoneySerializerField(positive=False, required=False, allow_null=True)
    questions = QuestionSerializer(many=True, required=False, max_length=MAX_QUESTIONS)
    asks_document = serializers.BooleanField(required=False)
    opens_on = serializers.DateField(required=False, allow_null=True)
    closes_on = serializers.DateField(required=False, allow_null=True)
    publish = serializers.BooleanField(
        required=False, default=False, help_text="Open it to applicants at once (new ones only)."
    )

    class Meta:
        ref_name = "HrVacancyWrite"


class VacancyPatchSerializer(VacancyWriteSerializer):
    title = serializers.CharField(max_length=services.TITLE_MAX, required=False)

    class Meta:
        ref_name = "HrVacancyPatch"


class ApplicantSerializer(serializers.ModelSerializer):
    vacancy = serializers.SerializerMethodField()
    member = serializers.SerializerMethodField(help_text="Who they became, once hired.")
    has_document = serializers.SerializerMethodField()

    class Meta:
        model = Applicant
        fields = (
            "id",
            "vacancy",
            "name",
            "phone",
            "telegram_username",
            "language",
            "stage",
            "stage_changed_at",
            "source",
            "answers",
            "has_document",
            "rejected_reason",
            "member",
            "hired_at",
            "created_at",
        )
        read_only_fields = fields
        ref_name = "HrApplicant"

    @extend_schema_field(NamedSerializer)
    def get_vacancy(self, applicant: Applicant) -> dict:
        return {"id": applicant.vacancy_id, "name": applicant.vacancy.title}

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_member(self, applicant: Applicant) -> dict | None:
        return person_ref(applicant.membership)

    def get_has_document(self, applicant: Applicant) -> bool:
        return bool(applicant.document)


class ApplicantEventSerializer(serializers.ModelSerializer):
    by = serializers.SerializerMethodField()

    class Meta:
        model = ApplicantEvent
        fields = (
            "id",
            "kind",
            "from_stage",
            "to_stage",
            "text",
            "message",
            "notified",
            "by",
            "created_at",
        )
        read_only_fields = fields
        ref_name = "HrApplicantEvent"

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_by(self, event: ApplicantEvent) -> dict | None:
        return person_ref(event.by)


class ApplicantDetailSerializer(ApplicantSerializer):
    document = PrivateFileSerializerField(
        check="hr.applicant", help_text="A signed link to their diploma photo, when they sent one."
    )
    events = serializers.SerializerMethodField(help_text="Oldest first.")

    class Meta(ApplicantSerializer.Meta):
        fields = (*ApplicantSerializer.Meta.fields, "document", "events")
        read_only_fields = fields
        ref_name = "HrApplicantDetail"

    @extend_schema_field(ApplicantEventSerializer(many=True))
    def get_events(self, applicant: Applicant) -> list[dict]:
        events = applicant.events.select_related("by__user").order_by("created_at", "pk")
        return ApplicantEventSerializer(events, many=True).data


class MoveSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=[(stage, stage) for stage in queries.OPEN_STAGES])
    message = serializers.CharField(
        max_length=services.MESSAGE_MAX, required=False, allow_blank=True, default=""
    )
    notify = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Tell them in the bot. Empty: for an interview or an offer, or with a message.",
    )

    class Meta:
        ref_name = "HrApplicantMove"


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=services.REASON_MAX, help_text="For the team.")
    message = serializers.CharField(
        max_length=services.MESSAGE_MAX, required=False, allow_blank=True, default=""
    )
    notify = serializers.BooleanField(required=False, default=True)

    class Meta:
        ref_name = "HrApplicantReject"


class HireSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Only for a vacancy without a branch."
    )
    message = serializers.CharField(
        max_length=services.MESSAGE_MAX, required=False, allow_blank=True, default=""
    )

    class Meta:
        ref_name = "HrApplicantHire"


class NoteSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=services.NOTE_MAX)

    class Meta:
        ref_name = "HrApplicantNote"
