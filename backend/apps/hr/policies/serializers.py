"""Shapes of the policy endpoints (owner dashboard and mini app).

The context carries `membership` (the viewer), `today`, and for lists `tallies` (policy id →
Tally) and `names` (user id → how the company names that person).
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import signed_url
from apps.hr.models import Policy, PolicyCategory, PolicyVersion
from apps.hr.policies import queries
from apps.hr.serializers import BranchRefSerializer, NamedSerializer, PersonRefSerializer
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
# What a version's file is, for the right icon and viewer.
FILE_TYPES = ("pdf", "image")


def file_type(version: PolicyVersion) -> str | None:
    if not version.file:
        return None
    return "image" if version.file.name.lower().endswith(IMAGE_SUFFIXES) else "pdf"


def file_link(version: PolicyVersion, user) -> str:
    """A signed link to a version's file, saved as "<title> v<number>.<ext>"."""
    extension = version.file.name.rsplit(".", 1)[-1]
    title = "".join(ch for ch in version.policy.title if ch.isalnum() or ch in " -_")[:60]
    return signed_url(
        version.file,
        user=user,
        company_id=version.company_id,
        check=f"hr.policy:{version.pk}",
        filename=f"{title.strip() or 'policy'} v{version.number}.{extension}",
    )


def due_on(policy: Policy, company=None):
    """The deadline of the people asked when the version that asks was published."""
    version = policy.ack_version
    if not policy.requires_ack or version is None or version.published_at is None:
        return None
    return queries.due_from(policy, queries.today(company or policy.company, version.published_at))


class TallySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    signed = serializers.IntegerField()
    waiting = serializers.IntegerField()
    late = serializers.IntegerField()

    class Meta:
        ref_name = "HrPolicyTally"


class VersionRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    published_at = serializers.DateTimeField(allow_null=True)
    asks_again = serializers.BooleanField()

    class Meta:
        ref_name = "HrPolicyVersionRef"


class DraftRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    updated_at = serializers.DateTimeField()

    class Meta:
        ref_name = "HrPolicyDraftRef"


def _version_ref(version: PolicyVersion | None) -> dict | None:
    if version is None:
        return None
    return {
        "id": version.pk,
        "number": version.number,
        "published_at": version.published_at,
        "asks_again": version.asks_again,
    }


class PolicySerializer(serializers.ModelSerializer):
    """A policy in the list: what it is, who it applies to, its version and how the signing
    goes among the people in the viewer's scope (`tally`, null while nobody is asked)."""

    category = serializers.ChoiceField(PolicyCategory.choices, read_only=True)
    positions = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField(help_text="The version in force.")
    ack_number = serializers.SerializerMethodField(
        help_text="The version signatures are asked for (a small edit after it keeps them)."
    )
    draft = serializers.SerializerMethodField()
    tally = serializers.SerializerMethodField()
    due_on = serializers.SerializerMethodField(
        help_text="The deadline of those asked when that version came out."
    )
    can_change = serializers.SerializerMethodField()

    class Meta:
        model = Policy
        fields = (
            "id",
            "title",
            "category",
            "requires_ack",
            "ack_within_days",
            "is_active",
            "positions",
            "branches",
            "version",
            "ack_number",
            "draft",
            "tally",
            "due_on",
            "can_change",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
        ref_name = "HrPolicy"

    @extend_schema_field(NamedSerializer(many=True))
    def get_positions(self, policy: Policy):
        return [{"id": row.pk, "name": row.name} for row in policy.positions.all()]

    @extend_schema_field(BranchRefSerializer(many=True))
    def get_branches(self, policy: Policy):
        return [branch_ref(row) for row in policy.branches.all()]

    @extend_schema_field(VersionRefSerializer(allow_null=True))
    def get_version(self, policy: Policy):
        return _version_ref(policy.current_version)

    def get_ack_number(self, policy: Policy) -> int | None:
        if not policy.requires_ack or policy.ack_version is None:
            return None
        return policy.ack_version.number

    @extend_schema_field(DraftRefSerializer(allow_null=True))
    def get_draft(self, policy: Policy):
        drafts = getattr(policy, "drafts", None)
        draft = drafts[0] if drafts else (None if drafts is not None else queries.draft_of(policy))
        if draft is None:
            return None
        return {"id": draft.pk, "number": draft.number, "updated_at": draft.updated_at}

    @extend_schema_field(TallySerializer(allow_null=True))
    def get_tally(self, policy: Policy):
        if not (policy.is_active and policy.requires_ack and policy.ack_version_id):
            return None
        found = self.context.get("tallies", {}).get(policy.pk)
        return None if found is None else TallySerializer(found).data

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_due_on(self, policy: Policy):
        return due_on(policy, self.context.get("company"))

    def get_can_change(self, policy: Policy) -> bool:
        member = self.context["membership"]
        return member.has_perm(Perm.HR_MANAGE) and queries.may_change(member, policy)


class VersionSerializer(serializers.ModelSerializer):
    published_by = serializers.SerializerMethodField()
    is_draft = serializers.BooleanField(read_only=True)
    has_file = serializers.SerializerMethodField()
    file_type = serializers.SerializerMethodField()

    class Meta:
        model = PolicyVersion
        fields = (
            "id",
            "number",
            "change_note",
            "asks_again",
            "published_at",
            "published_by",
            "is_draft",
            "has_file",
            "file_type",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
        ref_name = "HrPolicyVersion"

    def get_published_by(self, version: PolicyVersion) -> str | None:
        if version.published_by_id is None:
            return None
        return self.context.get("names", {}).get(version.published_by_id) or str(
            version.published_by
        )

    def get_has_file(self, version: PolicyVersion) -> bool:
        return bool(version.file)

    @extend_schema_field(
        serializers.ChoiceField(choices=FILE_TYPES, allow_null=True, read_only=True)
    )
    def get_file_type(self, version: PolicyVersion):
        return file_type(version)


class VersionDetailSerializer(VersionSerializer):
    """A version with its text, and a short-lived link to its file."""

    file_url = serializers.SerializerMethodField(help_text="Signed link (minutes).")

    class Meta(VersionSerializer.Meta):
        fields = (*VersionSerializer.Meta.fields, "body", "body_text", "file_url")
        read_only_fields = fields
        ref_name = "HrPolicyVersionDetail"

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_url(self, version: PolicyVersion):
        if not version.file:
            return None
        return file_link(version, self.context["request"].user)


class PolicyDetailSerializer(PolicySerializer):
    """One policy: its list shape, every version (newest first) and how many people it applies
    to now."""

    versions = serializers.SerializerMethodField()
    audience_count = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta(PolicySerializer.Meta):
        fields = (*PolicySerializer.Meta.fields, "versions", "audience_count", "created_by")
        read_only_fields = fields
        ref_name = "HrPolicyDetail"

    @extend_schema_field(VersionSerializer(many=True))
    def get_versions(self, policy: Policy):
        rows = policy.versions.select_related("published_by").order_by("-number")
        return VersionSerializer(rows, many=True, context=self.context).data

    def get_audience_count(self, policy: Policy) -> int:
        return queries.audience(policy).count()

    def get_created_by(self, policy: Policy) -> str | None:
        if policy.created_by_id is None:
            return None
        return self.context.get("names", {}).get(policy.created_by_id) or str(policy.created_by)


class PolicyWriteSerializer(serializers.Serializer):
    """A policy's settings; on create also the first draft's text."""

    title = serializers.CharField(max_length=150, required=False)
    category = serializers.ChoiceField(PolicyCategory.choices, required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    requires_ack = serializers.BooleanField(required=False)
    ack_within_days = serializers.IntegerField(min_value=1, max_value=90, required=False)
    is_active = serializers.BooleanField(required=False)
    body = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    change_note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "HrPolicyWrite"


class DraftWriteSerializer(serializers.Serializer):
    """The next version's text, file (multipart) and note; `remove_file` drops the file."""

    body = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    change_note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    file = serializers.FileField(required=False, allow_null=True)
    remove_file = serializers.BooleanField(required=False, default=False)

    class Meta:
        ref_name = "HrPolicyDraftWrite"


class PublishSerializer(serializers.Serializer):
    asks_again = serializers.BooleanField(
        required=False,
        default=True,
        help_text="False for a small edit: nobody is asked again, signatures stay.",
    )
    change_note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "HrPolicyPublish"


class RemindSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )

    class Meta:
        ref_name = "HrPolicyRemind"


class RemindedSerializer(serializers.Serializer):
    reminded = serializers.IntegerField()

    class Meta:
        ref_name = "HrPolicyReminded"


class AudienceSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="People it would apply to now.")
    people = PersonRefSerializer(many=True, help_text="The first few, in the viewer's scope.")

    class Meta:
        ref_name = "HrPolicyAudience"


class SignatureSerializer(serializers.Serializer):
    """One row of the people grid."""

    member = PersonRefSerializer()
    position = NamedSerializer(allow_null=True)
    branch = BranchRefSerializer(allow_null=True)
    state = serializers.ChoiceField(choices=queries.STATES)
    asked_at = serializers.DateTimeField()
    due_on = serializers.DateField()
    signed_at = serializers.DateTimeField(allow_null=True)
    signed_number = serializers.IntegerField(allow_null=True)
    reminded_at = serializers.DateTimeField(allow_null=True)
    earlier_signed_at = serializers.DateTimeField(
        allow_null=True, help_text="When they signed an earlier version (if they did)."
    )

    class Meta:
        ref_name = "HrPolicySignature"


def signature_payload(row, day, earlier: dict) -> dict:
    person = row.membership
    return {
        "member": person_ref(person),
        "position": {"id": person.position.pk, "name": person.position.name}
        if person.position
        else None,
        "branch": branch_ref(person.home_branch),
        "state": queries.state(row, day),
        "asked_at": row.asked_at,
        "due_on": row.due_on,
        "signed_at": row.acknowledged_at,
        "signed_number": row.signed_version.number if row.signed_version else None,
        "reminded_at": row.reminded_at,
        "earlier_signed_at": earlier.get(person.pk),
    }


class PolicyRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    category = serializers.ChoiceField(PolicyCategory.choices)

    class Meta:
        ref_name = "HrPolicyRef"


class StandingSerializer(serializers.Serializer):
    """Where one person stands on one policy that applies to them."""

    policy = PolicyRefSerializer()
    number = serializers.IntegerField(help_text="The version in force.")
    state = serializers.ChoiceField(choices=queries.MY_STATES)
    due_on = serializers.DateField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    signed_number = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "HrPolicyStanding"


class PastSignatureSerializer(serializers.Serializer):
    policy = PolicyRefSerializer()
    number = serializers.IntegerField(help_text="The version that asked.")
    signed_number = serializers.IntegerField(allow_null=True)
    signed_at = serializers.DateTimeField()

    class Meta:
        ref_name = "HrPolicyPastSignature"


class PersonPoliciesSerializer(serializers.Serializer):
    current = StandingSerializer(many=True)
    history = PastSignatureSerializer(many=True)

    class Meta:
        ref_name = "HrPersonPolicies"


def policy_ref(policy: Policy) -> dict:
    return {"id": policy.pk, "title": policy.title, "category": policy.category}


def standing_payload(item: queries.Standing) -> dict:
    return {
        "policy": policy_ref(item.policy),
        "number": item.policy.current_version.number,
        "state": item.state,
        "due_on": item.due_on,
        "signed_at": item.signed_at,
        "signed_number": item.signed_number,
    }


# The mini app ------------------------------------------------------------------------------


class MyPolicySerializer(serializers.Serializer):
    """A policy in my list."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    category = serializers.ChoiceField(PolicyCategory.choices)
    number = serializers.IntegerField(help_text="The version in force.")
    published_at = serializers.DateTimeField()
    state = serializers.ChoiceField(choices=queries.MY_STATES)
    due_on = serializers.DateField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    signed_number = serializers.IntegerField(allow_null=True)
    has_file = serializers.BooleanField()

    class Meta:
        ref_name = "HrMyPolicy"


class MyPolicyDetailSerializer(MyPolicySerializer):
    """One of my policies to read (and sign): the text in force and what changed in it."""

    version_id = serializers.IntegerField(help_text="Sign this version.")
    body = serializers.CharField()
    change_note = serializers.CharField()
    asks_again = serializers.BooleanField(
        help_text="False when the version in force is a small edit of the one signed."
    )
    file_type = serializers.ChoiceField(choices=FILE_TYPES, allow_null=True)

    class Meta:
        ref_name = "HrMyPolicyDetail"


def my_policy_payload(item: queries.Standing, *, detail: bool = False) -> dict:
    policy, version = item.policy, item.policy.current_version
    data = {
        "id": policy.pk,
        "title": policy.title,
        "category": policy.category,
        "number": version.number,
        "published_at": version.published_at,
        "state": item.state,
        "due_on": item.due_on,
        "signed_at": item.signed_at,
        "signed_number": item.signed_number,
        "has_file": bool(version.file),
    }
    if detail:
        data |= {
            "version_id": version.pk,
            "body": version.body,
            "change_note": version.change_note,
            "asks_again": version.asks_again,
            "file_type": file_type(version),
        }
    return data
