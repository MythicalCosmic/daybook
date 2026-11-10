"""Shapes of the performance review endpoints (owner dashboard and mini app). The context carries
`membership` (the viewer) and `today`; a round's rows also `late` ({review id: parts}) and
`bonuses` ({adjustment id: summary}). Someone's pay shows only with payroll.view; the person
reads their own review, and only once it is published, in the mini app."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import MoneySerializerField
from apps.hr.serializers import BranchRefSerializer, PersonRefSerializer
from apps.lifecycle import review_queries, reviews
from apps.lifecycle.models import JobChange, Review, ReviewCycle, ReviewGoal
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref

SELF_STATES = ("not_started", "draft", "sent")
MANAGER_STATES = ("not_started", "draft", "published")
OUTCOME_STATES = ("waiting", "approved", "applied", "rejected")
LATE_PARTS = ("self", "manager")
MY_STATES = ("todo", "draft", "sent", "published")


def self_state(review: Review) -> str:
    if review.self_sent_at is not None:
        return "sent"
    return "draft" if review.self_saved_at is not None else "not_started"


def manager_state(review: Review) -> str:
    if review.published_at is not None:
        return "published"
    return "draft" if review.manager_saved_at is not None else "not_started"


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "LifecycleReviewRef"


def _ref(row) -> dict | None:
    return {"id": row.pk, "name": row.name} if row is not None else None


class AnswerSerializer(serializers.Serializer):
    rating = serializers.IntegerField(allow_null=True, required=False, min_value=1, max_value=5)
    text = serializers.CharField(allow_blank=True, required=False)

    class Meta:
        ref_name = "LifecycleReviewAnswer"


class QuestionSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField([(kind, kind) for kind in reviews.KINDS])
    text = serializers.CharField()
    key = serializers.CharField(
        allow_blank=True, help_text="The template question it is, while its words are untouched."
    )

    class Meta:
        ref_name = "LifecycleReviewQuestion"


class QuestionWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField([(kind, kind) for kind in reviews.KINDS])
    text = serializers.CharField(max_length=reviews.MAX_QUESTION)
    key = serializers.CharField(allow_blank=True, required=False, default="")

    class Meta:
        ref_name = "LifecycleReviewQuestionWrite"


class ProgressSerializer(serializers.Serializer):
    people = serializers.IntegerField()
    self_sent = serializers.IntegerField()
    published = serializers.IntegerField()
    acknowledged = serializers.IntegerField()
    late = serializers.IntegerField()
    self_late = serializers.IntegerField()
    manager_late = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleReviewProgress"


class AudienceSerializer(serializers.Serializer):
    positions = RefSerializer(many=True)
    branches = RefSerializer(many=True)

    class Meta:
        ref_name = "LifecycleReviewAudience"


class RoundCanSerializer(serializers.Serializer):
    run = serializers.BooleanField()
    edit = serializers.BooleanField()
    open = serializers.BooleanField()
    advance = serializers.BooleanField()
    close = serializers.BooleanField()
    remind = serializers.BooleanField()
    delete = serializers.BooleanField()

    class Meta:
        ref_name = "LifecycleReviewRoundCan"


class RoundSerializer(serializers.ModelSerializer):
    """A round with how far it has got for the viewer (the reviews they see)."""

    status = serializers.ChoiceField(ReviewCycle.Status.choices, read_only=True)
    audience = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    mine = serializers.SerializerMethodField(help_text="Reviews waiting for the viewer to write.")
    reviewers_begin_on = serializers.SerializerMethodField(
        help_text="Before the reviewers' part: the day it begins by itself."
    )
    created_by = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    class Meta:
        model = ReviewCycle
        fields = (
            "id",
            "name",
            "period_start",
            "period_end",
            "status",
            "self_due_on",
            "manager_due_on",
            "reviewers_begin_on",
            "audience",
            "questions",
            "progress",
            "mine",
            "created_by",
            "opened_at",
            "manager_at",
            "closed_at",
            "created_at",
            "can",
        )
        read_only_fields = fields
        ref_name = "LifecycleReviewRound"

    def _viewer(self):
        return self.context["membership"]

    @extend_schema_field(AudienceSerializer)
    def get_audience(self, cycle: ReviewCycle) -> dict:
        return {
            "positions": [_ref(row) for row in cycle.positions.all()],
            "branches": [_ref(row) for row in cycle.branches.all()],
        }

    @extend_schema_field(QuestionSerializer(many=True))
    def get_questions(self, cycle: ReviewCycle) -> list[dict]:
        return reviews.shown_questions(cycle)

    def _rows(self, cycle: ReviewCycle) -> list[Review]:
        cache = self.context.setdefault("_rows", {})
        if cycle.pk not in cache:
            cache[cycle.pk] = list(review_queries.visible_reviews(self._viewer(), cycle))
        return cache[cycle.pk]

    @extend_schema_field(ProgressSerializer)
    def get_progress(self, cycle: ReviewCycle) -> dict:
        return review_queries.progress(cycle, self._rows(cycle), today=self.context["today"])

    def get_mine(self, cycle: ReviewCycle) -> int:
        viewer = self._viewer()
        if cycle.status != ReviewCycle.Status.MANAGER:
            return 0
        return sum(
            1
            for review in self._rows(cycle)
            if review.reviewer_id == viewer.pk and review.published_at is None
        )

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_reviewers_begin_on(self, cycle: ReviewCycle):
        if cycle.status not in (ReviewCycle.Status.DRAFT, ReviewCycle.Status.SELF):
            return None
        return reviews.reviewers_begin_on(cycle)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_created_by(self, cycle: ReviewCycle) -> dict | None:
        return person_ref(cycle.created_by)

    @extend_schema_field(RoundCanSerializer)
    def get_can(self, cycle: ReviewCycle) -> dict:
        run = reviews.may_run(self._viewer(), cycle)
        status = cycle.status
        Status = ReviewCycle.Status
        return {
            "run": run,
            "edit": run and status != Status.CLOSED,
            "open": run and status == Status.DRAFT,
            "advance": run and status == Status.SELF,
            "close": run and status in reviews.OPEN,
            "remind": run and status in reviews.OPEN,
            "delete": run and status == Status.DRAFT,
        }


class RoundWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=reviews.MAX_NAME)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    self_due_on = serializers.DateField()
    manager_due_on = serializers.DateField()
    questions = QuestionWriteSerializer(many=True)
    positions = serializers.ListField(child=serializers.IntegerField(), required=False)
    branches = serializers.ListField(child=serializers.IntegerField(), required=False)
    open = serializers.BooleanField(
        required=False, default=False, help_text="Open it at once (everyone in it hears)."
    )

    class Meta:
        ref_name = "LifecycleReviewRoundWrite"


class RoundUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=reviews.MAX_NAME, required=False)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    self_due_on = serializers.DateField(required=False)
    manager_due_on = serializers.DateField(required=False)
    questions = QuestionWriteSerializer(many=True, required=False)
    positions = serializers.ListField(child=serializers.IntegerField(), required=False)
    branches = serializers.ListField(child=serializers.IntegerField(), required=False)

    class Meta:
        ref_name = "LifecycleReviewRoundUpdate"


class PreviewPersonSerializer(serializers.Serializer):
    member = PersonRefSerializer()
    position = serializers.CharField(allow_null=True)
    home_branch = BranchRefSerializer(allow_null=True)
    reviewer = PersonRefSerializer(allow_null=True)

    class Meta:
        ref_name = "LifecycleReviewPreviewPerson"


class PreviewReviewerSerializer(serializers.Serializer):
    reviewer = PersonRefSerializer(allow_null=True)
    people = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleReviewPreviewReviewer"


class PreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    reviewers = PreviewReviewerSerializer(many=True)
    people = PreviewPersonSerializer(many=True)

    class Meta:
        ref_name = "LifecycleReviewPreview"


class RemindedSerializer(serializers.Serializer):
    people = serializers.IntegerField()
    reviewers = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleReviewReminded"


# A round's people ----------------------------------------------------------------------------


class ReviewRowSerializer(serializers.ModelSerializer):
    """One person in a round, as its page lists them; the rating and outcome only for whoever
    may read the review."""

    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    reviewer = serializers.SerializerMethodField()
    self_state = serializers.SerializerMethodField()
    manager_state = serializers.SerializerMethodField()
    late = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    outcome = serializers.SerializerMethodField()
    outcome_state = serializers.SerializerMethodField()
    can_open = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id",
            "member",
            "position",
            "home_branch",
            "reviewer",
            "self_state",
            "self_sent_at",
            "manager_state",
            "published_at",
            "acknowledged_at",
            "reminded_at",
            "late",
            "rating",
            "outcome",
            "outcome_state",
            "can_open",
        )
        read_only_fields = fields
        ref_name = "LifecycleReviewRow"

    def _readable(self, review: Review) -> bool:
        return reviews.may_read(self.context["membership"], review)

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, review: Review) -> dict:
        return person_ref(review.membership)

    def get_position(self, review: Review) -> str | None:
        position = review.membership.position
        return position.name if position else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, review: Review) -> dict | None:
        return branch_ref(review.membership.home_branch)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_reviewer(self, review: Review) -> dict | None:
        return person_ref(review.reviewer)

    @extend_schema_field(serializers.ChoiceField([(s, s) for s in SELF_STATES]))
    def get_self_state(self, review: Review) -> str:
        return self_state(review)

    @extend_schema_field(serializers.ChoiceField([(s, s) for s in MANAGER_STATES]))
    def get_manager_state(self, review: Review) -> str:
        return manager_state(review)

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(LATE_PARTS)))
    def get_late(self, review: Review) -> list[str]:
        return (self.context.get("late") or {}).get(review.pk, [])

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_rating(self, review: Review) -> int | None:
        return review.rating if review.published_at and self._readable(review) else None

    @extend_schema_field(serializers.ChoiceField(Review.Outcome.choices, allow_null=True))
    def get_outcome(self, review: Review) -> str | None:
        return review.outcome if review.published_at and self._readable(review) else None

    @extend_schema_field(serializers.ChoiceField([(s, s) for s in OUTCOME_STATES], allow_null=True))
    def get_outcome_state(self, review: Review) -> str | None:
        if not review.published_at or not self._readable(review):
            return None
        return review_queries.outcome_state(review, self.context.get("bonuses") or {})

    def get_can_open(self, review: Review) -> bool:
        return self._readable(review)


# One review ----------------------------------------------------------------------------------


class TasksKpiSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    on_time = serializers.IntegerField()
    late = serializers.IntegerField()
    missed = serializers.IntegerField()
    on_time_percent = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "LifecycleReviewTasksKpi"


class AttendanceKpiSerializer(serializers.Serializer):
    scheduled_days = serializers.IntegerField()
    attended_days = serializers.IntegerField()
    absent_days = serializers.IntegerField()
    late_arrivals = serializers.IntegerField()
    late_minutes = serializers.IntegerField()
    leave_days = serializers.IntegerField()
    worked_hours = serializers.CharField()

    class Meta:
        ref_name = "LifecycleReviewAttendanceKpi"


class DisciplineKpiSerializer(serializers.Serializer):
    records = serializers.IntegerField()
    by_kind = serializers.DictField(child=serializers.IntegerField())

    class Meta:
        ref_name = "LifecycleReviewDisciplineKpi"


class SalesKpiSerializer(serializers.Serializer):
    shifts = serializers.IntegerField()
    net = serializers.CharField()
    receipts = serializers.IntegerField()
    avg_check = serializers.CharField()
    accuracy = serializers.CharField(allow_null=True)
    shortages = serializers.IntegerField()
    shortage_total = serializers.CharField()
    currency = serializers.CharField()

    class Meta:
        ref_name = "LifecycleReviewSalesKpi"


class LearningKpiSerializer(serializers.Serializer):
    completed = serializers.IntegerField()
    open = serializers.IntegerField()
    late = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleReviewLearningKpi"


class GoalsKpiSerializer(serializers.Serializer):
    open = serializers.IntegerField()
    done = serializers.IntegerField()
    missed = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleReviewGoalsKpi"


class KpisSerializer(serializers.Serializer):
    taken_at = serializers.DateTimeField()
    start = serializers.DateField()
    end = serializers.DateField()
    tasks = TasksKpiSerializer()
    attendance = AttendanceKpiSerializer(allow_null=True)
    discipline = DisciplineKpiSerializer()
    sales = SalesKpiSerializer(allow_null=True, help_text="Only with sales.view.")
    learning = LearningKpiSerializer(allow_null=True)
    goals = GoalsKpiSerializer(allow_null=True)

    class Meta:
        ref_name = "LifecycleReviewKpis"


class GoalSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(ReviewGoal.Status.choices, read_only=True)
    target = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True, allow_null=True, read_only=True
    )
    progress = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True, allow_null=True, read_only=True
    )

    class Meta:
        model = ReviewGoal
        fields = (
            "id",
            "title",
            "target",
            "unit",
            "progress",
            "due_on",
            "status",
            "note",
            "closed_at",
        )
        read_only_fields = fields
        ref_name = "LifecycleReviewGoal"


class GoalWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, allow_blank=True)
    due_on = serializers.DateField(allow_null=True, required=False)
    target = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, required=False
    )
    unit = serializers.CharField(max_length=30, allow_blank=True, required=False, default="")

    class Meta:
        ref_name = "LifecycleReviewGoalWrite"


class GoalUpdateSerializer(serializers.Serializer):
    progress = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, required=False
    )
    status = serializers.ChoiceField(ReviewGoal.Status.choices, required=False)
    note = serializers.CharField(max_length=300, allow_blank=True, required=False)

    class Meta:
        ref_name = "LifecycleReviewGoalUpdate"


class PaySerializer(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()
    pay_type = serializers.CharField()
    rounding_step = serializers.CharField(help_text="A raise rounds the new pay to this.")

    class Meta:
        ref_name = "LifecycleReviewPay"


class ChangeRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(JobChange.Status.choices)
    effective_on = serializers.DateField()
    parts = serializers.ListField(child=serializers.CharField())
    pay_before = serializers.CharField(allow_null=True, help_text="Only with payroll.view.")
    pay_after = serializers.CharField(allow_null=True, help_text="Only with payroll.view.")
    error = serializers.CharField(allow_blank=True)
    can_decide = serializers.BooleanField()

    class Meta:
        ref_name = "LifecycleReviewChange"


class BonusRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.CharField()
    currency = serializers.CharField()
    status = serializers.CharField(help_text="The adjustment's status in payroll.")
    period = serializers.DateField()

    class Meta:
        ref_name = "LifecycleReviewBonus"


class SelfPartSerializer(serializers.Serializer):
    visible = serializers.BooleanField(help_text="False until the reviewers' part begins.")
    state = serializers.ChoiceField([(s, s) for s in SELF_STATES])
    sent_at = serializers.DateTimeField(allow_null=True)
    answers = serializers.DictField(child=AnswerSerializer(), allow_null=True)
    average = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "LifecycleReviewSelfPart"


class EarlierSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    round = serializers.CharField()
    period_end = serializers.DateField()
    rating = serializers.IntegerField(allow_null=True)
    outcome = serializers.ChoiceField(Review.Outcome.choices)
    published_at = serializers.DateTimeField()

    class Meta:
        ref_name = "LifecycleReviewEarlier"


class ReviewCanSerializer(serializers.Serializer):
    write = serializers.BooleanField()
    pay = serializers.BooleanField(help_text="May give a raise or a bonus.")
    reassign = serializers.BooleanField()
    remove = serializers.BooleanField()
    goals = serializers.BooleanField(help_text="May mark the plan's goals.")

    class Meta:
        ref_name = "LifecycleReviewCan"


class RoundRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.ChoiceField(ReviewCycle.Status.choices)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    self_due_on = serializers.DateField()
    manager_due_on = serializers.DateField()

    class Meta:
        ref_name = "LifecycleReviewRoundRef"


class ReviewSerializer(serializers.ModelSerializer):
    """One review as its reviewer (or an owner) reads it."""

    round = serializers.SerializerMethodField()
    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    reviewer = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()
    self_part = serializers.SerializerMethodField()
    manager_answers = serializers.DictField(child=AnswerSerializer(), read_only=True)
    manager_state = serializers.SerializerMethodField()
    manager_average = serializers.SerializerMethodField()
    kpis = serializers.SerializerMethodField()
    outcome = serializers.ChoiceField(Review.Outcome.choices, read_only=True)
    raise_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, coerce_to_string=True, allow_null=True, read_only=True
    )
    bonus_amount = MoneySerializerField(allow_null=True, read_only=True)
    promotion_position = serializers.SerializerMethodField()
    goals = GoalSerializer(many=True, read_only=True)
    pay = serializers.SerializerMethodField(help_text="Their pay now, only with payroll.view.")
    job_change = serializers.SerializerMethodField()
    bonus = serializers.SerializerMethodField()
    outcome_state = serializers.SerializerMethodField()
    published_by = serializers.SerializerMethodField()
    earlier = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id",
            "round",
            "member",
            "position",
            "home_branch",
            "reviewer",
            "questions",
            "self_part",
            "manager_answers",
            "manager_state",
            "manager_average",
            "manager_saved_at",
            "kpis",
            "kpis_at",
            "rating",
            "summary",
            "outcome",
            "raise_percent",
            "bonus_amount",
            "bonus_currency",
            "promotion_position",
            "effective_on",
            "goals",
            "pay",
            "job_change",
            "bonus",
            "outcome_state",
            "published_at",
            "published_by",
            "acknowledged_at",
            "earlier",
            "can",
        )
        read_only_fields = fields
        ref_name = "LifecycleReview"

    def _viewer(self):
        return self.context["membership"]

    @extend_schema_field(RoundRefSerializer)
    def get_round(self, review: Review) -> dict:
        cycle = review.cycle
        return {
            "id": cycle.pk,
            "name": cycle.name,
            "status": cycle.status,
            "period_start": cycle.period_start,
            "period_end": cycle.period_end,
            "self_due_on": cycle.self_due_on,
            "manager_due_on": cycle.manager_due_on,
        }

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, review: Review) -> dict:
        return person_ref(review.membership)

    def get_position(self, review: Review) -> str | None:
        position = review.membership.position
        return position.name if position else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, review: Review) -> dict | None:
        return branch_ref(review.membership.home_branch)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_reviewer(self, review: Review) -> dict | None:
        return person_ref(review.reviewer)

    @extend_schema_field(QuestionSerializer(many=True))
    def get_questions(self, review: Review) -> list[dict]:
        return reviews.shown_questions(review.cycle)

    @extend_schema_field(SelfPartSerializer)
    def get_self_part(self, review: Review) -> dict:
        visible = reviews.self_visible(review)
        sent = review.self_sent_at is not None
        return {
            "visible": visible,
            "state": self_state(review),
            "sent_at": review.self_sent_at,
            "answers": review.self_answers if visible and sent else None,
            "average": str(reviews.average(review.cycle, review.self_answers))
            if visible and sent and reviews.average(review.cycle, review.self_answers) is not None
            else None,
        }

    @extend_schema_field(serializers.ChoiceField([(s, s) for s in MANAGER_STATES]))
    def get_manager_state(self, review: Review) -> str:
        return manager_state(review)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_manager_average(self, review: Review) -> str | None:
        value = reviews.average(review.cycle, review.manager_answers)
        return str(value) if value is not None else None

    @extend_schema_field(KpisSerializer(allow_null=True))
    def get_kpis(self, review: Review) -> dict | None:
        if not review.kpis:
            return None
        found = dict(review.kpis)
        if not self._viewer().has_perm(Perm.SALES_VIEW):
            found["sales"] = None
        return found

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_promotion_position(self, review: Review) -> dict | None:
        return _ref(review.promotion_position)

    @extend_schema_field(PaySerializer(allow_null=True))
    def get_pay(self, review: Review) -> dict | None:
        from apps.lifecycle import integrations

        viewer = self._viewer()
        if not viewer.has_perm(Perm.PAYROLL_VIEW):
            return None
        on = review.effective_on or self.context["today"]
        current = integrations.current_pay(review.membership, on=on)
        if current is None:
            return None
        return {**current, "rounding_step": f"{reviews.rounding_step(review.company):.2f}"}

    @extend_schema_field(ChangeRefSerializer(allow_null=True))
    def get_job_change(self, review: Review) -> dict | None:
        from apps.lifecycle import job_changes

        change = review.job_change
        if change is None:
            return None
        viewer = self._viewer()
        pay_before = pay_after = None
        if viewer.has_perm(Perm.PAYROLL_VIEW) and "pay" in (change.parts or []):
            pay_before = ((change.before or {}).get("pay") or {}).get("amount")
            pay_after = ((change.after or {}).get("pay") or {}).get("amount")
        return {
            "id": change.pk,
            "status": change.status,
            "effective_on": change.effective_on,
            "parts": list(change.parts or []),
            "pay_before": pay_before,
            "pay_after": pay_after,
            "error": change.error,
            "can_decide": change.status == JobChange.Status.PROPOSED
            and job_changes.may_decide(viewer, change),
        }

    def _bonuses(self, review: Review) -> dict:
        cache = self.context.setdefault("bonuses", {})
        if review.bonus_id and review.bonus_id not in cache:
            cache.update(review_queries.adjustments(review.company, [review.bonus_id]))
        return cache

    @extend_schema_field(BonusRefSerializer(allow_null=True))
    def get_bonus(self, review: Review) -> dict | None:
        if not review.bonus_id:
            return None
        return self._bonuses(review).get(review.bonus_id)

    @extend_schema_field(serializers.ChoiceField([(s, s) for s in OUTCOME_STATES], allow_null=True))
    def get_outcome_state(self, review: Review) -> str | None:
        if review.published_at is None:
            return None
        return review_queries.outcome_state(review, self._bonuses(review))

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_published_by(self, review: Review) -> dict | None:
        return person_ref(review.published_by)

    @extend_schema_field(EarlierSerializer(many=True))
    def get_earlier(self, review: Review) -> list[dict]:
        rows = (
            Review.objects.filter(membership_id=review.membership_id, published_at__isnull=False)
            .exclude(pk=review.pk)
            .select_related("cycle")
            .order_by("-published_at")[:3]
        )
        return [
            {
                "id": row.pk,
                "round": row.cycle.name,
                "period_end": row.cycle.period_end,
                "rating": row.rating,
                "outcome": row.outcome,
                "published_at": row.published_at,
            }
            for row in rows
        ]

    @extend_schema_field(ReviewCanSerializer)
    def get_can(self, review: Review) -> dict:
        viewer = self._viewer()
        run = reviews.may_run(viewer, review.cycle)
        unpublished = review.published_at is None and review.cycle.status != "closed"
        return {
            "write": reviews.may_write(viewer, review),
            "pay": reviews.may_propose_pay(viewer),
            "reassign": run and unpublished,
            "remove": run and unpublished,
            "goals": review.published_at is not None and reviews.may_read(viewer, review),
        }


class ManagerWriteSerializer(serializers.Serializer):
    answers = serializers.DictField(child=AnswerSerializer(), required=False)
    rating = serializers.IntegerField(min_value=1, max_value=5, allow_null=True, required=False)
    summary = serializers.CharField(
        max_length=reviews.MAX_SUMMARY, allow_blank=True, required=False
    )
    outcome = serializers.ChoiceField(Review.Outcome.choices, required=False)
    raise_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True, required=False
    )
    bonus_amount = MoneySerializerField(allow_null=True, required=False)
    promotion_position_id = serializers.IntegerField(allow_null=True, required=False)
    effective_on = serializers.DateField(allow_null=True, required=False)
    goals = GoalWriteSerializer(many=True, required=False)

    class Meta:
        ref_name = "LifecycleReviewManagerWrite"


class ReassignSerializer(serializers.Serializer):
    reviewer_id = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleReviewReassign"


# Results -------------------------------------------------------------------------------------


class QuestionResultSerializer(serializers.Serializer):
    id = serializers.CharField()
    text = serializers.CharField()
    self_average = serializers.CharField(allow_null=True)
    manager_average = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "LifecycleReviewQuestionResult"


class BranchResultSerializer(serializers.Serializer):
    branch = RefSerializer(allow_null=True)
    people = serializers.IntegerField()
    average = serializers.CharField(allow_null=True)
    raises = serializers.IntegerField()
    bonuses = serializers.IntegerField()
    promotions = serializers.IntegerField()
    plans = serializers.IntegerField()
    raise_cost = serializers.CharField(allow_null=True, help_text="Only with payroll.view.")
    bonus_total = serializers.CharField(allow_null=True, help_text="Only with payroll.view.")

    class Meta:
        ref_name = "LifecycleReviewBranchResult"


class CostSerializer(serializers.Serializer):
    currency = serializers.CharField()
    raises_monthly = serializers.CharField(help_text="Approved raises: what they add a month.")
    raises_waiting = serializers.CharField(help_text="Raises still waiting for approval.")
    bonuses = serializers.CharField(help_text="Approved bonuses.")
    bonuses_waiting = serializers.CharField()

    class Meta:
        ref_name = "LifecycleReviewCost"


class ResultsSerializer(serializers.Serializer):
    people = serializers.IntegerField()
    published = serializers.IntegerField()
    average = serializers.CharField(allow_null=True)
    spread = serializers.DictField(
        child=serializers.IntegerField(), help_text="How many people got each rating, 1 to 5."
    )
    outcomes = serializers.DictField(child=serializers.IntegerField())
    questions = QuestionResultSerializer(many=True)
    by_branch = BranchResultSerializer(many=True)
    cost = CostSerializer(allow_null=True, help_text="Only with payroll.view.")

    class Meta:
        ref_name = "LifecycleReviewResults"


# Person 360's career line --------------------------------------------------------------------


class CareerReviewSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    round = RefSerializer()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    published_at = serializers.DateTimeField()
    rating = serializers.IntegerField(allow_null=True)
    outcome = serializers.ChoiceField(Review.Outcome.choices)
    can_open = serializers.BooleanField()

    class Meta:
        ref_name = "LifecycleCareerReview"


def career_reviews(rows, *, viewer) -> list[dict]:
    return [
        {
            "id": review.pk,
            "round": {"id": review.cycle_id, "name": review.cycle.name},
            "period_start": review.cycle.period_start,
            "period_end": review.cycle.period_end,
            "published_at": review.published_at,
            "rating": review.rating,
            "outcome": review.outcome,
            "can_open": reviews.may_read(viewer, review),
        }
        for review in rows
    ]


# The mini app --------------------------------------------------------------------------------


class MyRoundSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.ChoiceField(ReviewCycle.Status.choices)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    self_due_on = serializers.DateField()

    class Meta:
        ref_name = "LifecycleMyReviewRound"


def my_state(review: Review) -> str:
    if review.published_at is not None:
        return "published"
    if review.self_sent_at is not None:
        return "sent"
    return "draft" if review.self_saved_at is not None else "todo"


def _my_round(review: Review) -> dict:
    cycle = review.cycle
    return {
        "id": cycle.pk,
        "name": cycle.name,
        "status": cycle.status,
        "period_start": cycle.period_start,
        "period_end": cycle.period_end,
        "self_due_on": cycle.self_due_on,
    }


class MyReviewRowSerializer(serializers.ModelSerializer):
    round = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    can_answer = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    outcome = serializers.SerializerMethodField()
    late = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id",
            "round",
            "state",
            "can_answer",
            "self_sent_at",
            "published_at",
            "acknowledged_at",
            "rating",
            "outcome",
            "late",
        )
        read_only_fields = fields
        ref_name = "LifecycleMyReviewRow"

    @extend_schema_field(MyRoundSerializer)
    def get_round(self, review: Review) -> dict:
        return _my_round(review)

    @extend_schema_field(serializers.ChoiceField([(s, s) for s in MY_STATES]))
    def get_state(self, review: Review) -> str:
        return my_state(review)

    def get_can_answer(self, review: Review) -> bool:
        return (
            review.cycle.status in reviews.OPEN
            and review.self_sent_at is None
            and review.published_at is None
        )

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_rating(self, review: Review) -> int | None:
        return review.rating if review.published_at else None

    @extend_schema_field(serializers.ChoiceField(Review.Outcome.choices, allow_null=True))
    def get_outcome(self, review: Review) -> str | None:
        return review.outcome if review.published_at else None

    def get_late(self, review: Review) -> bool:
        return (
            review.self_sent_at is None
            and review.published_at is None
            and review.cycle.status in reviews.OPEN
            and self.context["today"] > review.cycle.self_due_on
        )


class MyChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(OUTCOME_STATES, allow_null=True)
    effective_on = serializers.DateField(allow_null=True)
    position = serializers.CharField(allow_null=True)
    pay_before = serializers.CharField(allow_null=True, help_text="Their own pay.")
    pay_after = serializers.CharField(allow_null=True, help_text="Their own pay.")
    currency = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "LifecycleMyReviewChange"


class MyReviewSerializer(MyReviewRowSerializer):
    """The person's own review: the questions and their answers; once published, their
    reviewer's answers, the rating, the summary, what follows and the goals."""

    questions = serializers.SerializerMethodField()
    answers = serializers.SerializerMethodField()
    reviewer = serializers.SerializerMethodField()
    manager_answers = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    raise_percent = serializers.SerializerMethodField()
    bonus = serializers.SerializerMethodField()
    change = serializers.SerializerMethodField()
    goals = serializers.SerializerMethodField()
    kpis = serializers.SerializerMethodField()

    class Meta(MyReviewRowSerializer.Meta):
        fields = (
            *MyReviewRowSerializer.Meta.fields,
            "questions",
            "answers",
            "self_saved_at",
            "reviewer",
            "manager_answers",
            "summary",
            "raise_percent",
            "bonus",
            "change",
            "goals",
            "kpis",
        )
        read_only_fields = fields
        ref_name = "LifecycleMyReview"

    def _published(self, review: Review) -> bool:
        return review.published_at is not None

    @extend_schema_field(QuestionSerializer(many=True))
    def get_questions(self, review: Review) -> list[dict]:
        return reviews.shown_questions(review.cycle)

    @extend_schema_field(serializers.DictField(child=AnswerSerializer()))
    def get_answers(self, review: Review) -> dict:
        return review.self_answers or {}

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reviewer(self, review: Review) -> str | None:
        return str(review.reviewer) if review.reviewer_id else None

    @extend_schema_field(serializers.DictField(child=AnswerSerializer(), allow_null=True))
    def get_manager_answers(self, review: Review) -> dict | None:
        return review.manager_answers if self._published(review) else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_summary(self, review: Review) -> str | None:
        return review.summary if self._published(review) else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_raise_percent(self, review: Review) -> str | None:
        if not self._published(review) or review.raise_percent is None:
            return None
        return f"{review.raise_percent:.2f}"

    @extend_schema_field(BonusRefSerializer(allow_null=True))
    def get_bonus(self, review: Review) -> dict | None:
        if not self._published(review) or not review.bonus_id:
            return None
        return review_queries.adjustments(review.company, [review.bonus_id]).get(review.bonus_id)

    @extend_schema_field(MyChangeSerializer(allow_null=True))
    def get_change(self, review: Review) -> dict | None:
        if not self._published(review) or review.outcome not in reviews.CHANGE_OUTCOMES:
            return None
        change = review.job_change
        pay = change is not None and "pay" in (change.parts or [])
        before = ((change.before or {}).get("pay") or {}) if pay else {}
        after = ((change.after or {}).get("pay") or {}) if pay else {}
        return {
            "status": review_queries.outcome_state(review, {}),
            "effective_on": change.effective_on if change else review.effective_on,
            "position": review.promotion_position.name if review.promotion_position_id else None,
            "pay_before": before.get("amount"),
            "pay_after": after.get("amount"),
            "currency": after.get("currency"),
        }

    @extend_schema_field(GoalSerializer(many=True))
    def get_goals(self, review: Review) -> list[dict]:
        if not self._published(review):
            return []
        return GoalSerializer(review.goals.all(), many=True).data

    @extend_schema_field(KpisSerializer(allow_null=True))
    def get_kpis(self, review: Review) -> dict | None:
        return review.kpis if self._published(review) and review.kpis else None


class MyGoalSerializer(GoalSerializer):
    round = serializers.CharField(source="review.cycle.name", read_only=True)
    review_id = serializers.IntegerField(read_only=True)

    class Meta(GoalSerializer.Meta):
        fields = (*GoalSerializer.Meta.fields, "round", "review_id")
        read_only_fields = fields
        ref_name = "LifecycleMyReviewGoal"


class MyReviewsSerializer(serializers.Serializer):
    open = MyReviewRowSerializer(many=True, help_text="Rounds waiting for my answers or sent.")
    past = MyReviewRowSerializer(many=True, help_text="Published, newest first.")
    goals = MyGoalSerializer(many=True, help_text="My open goals.")

    class Meta:
        ref_name = "LifecycleMyReviews"


class SelfWriteSerializer(serializers.Serializer):
    answers = serializers.DictField(child=AnswerSerializer())

    class Meta:
        ref_name = "LifecycleMyReviewWrite"


class SelfSendSerializer(serializers.Serializer):
    answers = serializers.DictField(child=AnswerSerializer(), required=False)

    class Meta:
        ref_name = "LifecycleMyReviewSend"
