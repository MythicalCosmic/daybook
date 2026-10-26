"""Owner endpoints of team links (one link or QR code that adds many people at once), mounted
at `/api/v1/owner/companies/<int:company_id>/` (members.approve):

    GET    join-links/          the links the viewer sees, working ones first
    POST   join-links/          a new link
    GET    join-links/{id}/     one link and the people who joined through it (the live screen)
    PATCH  join-links/{id}/     change it; `is_active` stops it or turns it back on
    DELETE join-links/{id}/     delete it (people who joined stay)
"""

from datetime import timedelta

from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import OwnerViewSet
from apps.members import join_links
from apps.members.models import AccessRole, JoinLink, Membership, Position
from apps.members.owner_api import NamedSerializer
from apps.members.permissions import Perm
from apps.members.queries import photo_url

# The live screen lists this many of the newest people.
PEOPLE_SHOWN = 100


def _ref(row) -> dict | None:
    return {"id": row.pk, "name": row.name} if row is not None else None


class JoinLinkSerializer(serializers.ModelSerializer):
    link = serializers.CharField(read_only=True, help_text='"" until the bot username is set.')
    start_param = serializers.CharField(read_only=True)
    branch = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField(help_text="Empty: the default role.")
    default_role = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = JoinLink
        fields = (
            "id",
            "name",
            "link",
            "start_param",
            "auto_approve",
            "branch",
            "role",
            "default_role",
            "position",
            "max_uses",
            "uses",
            "expires_at",
            "is_active",
            "status",
            "created_by",
            "created_at",
            "can_edit",
        )
        read_only_fields = fields

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_branch(self, link: JoinLink) -> dict | None:
        return _ref(link.branch)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_role(self, link: JoinLink) -> dict | None:
        return _ref(link.role)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_default_role(self, link: JoinLink) -> dict | None:
        return _ref(self.context.get("default_role"))

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, link: JoinLink) -> dict | None:
        return _ref(link.position)

    @extend_schema_field(serializers.ChoiceField(choices=JoinLink.Status.choices))
    def get_status(self, link: JoinLink) -> str:
        return link.status_at(self.context.get("now") or timezone.now())

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_created_by(self, link: JoinLink) -> dict | None:
        maker = link.created_by
        if maker is None:
            return None
        return {"id": maker.pk, "name": maker.full_name or str(maker.user)}

    def get_can_edit(self, link: JoinLink) -> bool:
        return join_links.may_edit(
            self.context["membership"], link, default=self.context.get("default_role")
        )


class JoinLinkPersonSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    onboarded = serializers.SerializerMethodField()
    joined_at = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ("id", "name", "photo_url", "position", "status", "onboarded", "joined_at")
        read_only_fields = fields

    def get_name(self, person: Membership) -> str:
        return person.full_name or person.user.get_full_name() or str(person.user)

    def get_photo_url(self, person: Membership) -> str | None:
        return photo_url(person)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, person: Membership) -> dict | None:
        return _ref(person.position)

    def get_onboarded(self, person: Membership) -> bool:
        return person.onboarded_at is not None

    @extend_schema_field(serializers.DateTimeField())
    def get_joined_at(self, person: Membership) -> str:
        return (person.onboarded_at or person.created_at).isoformat()


class JoinLinkDetailSerializer(JoinLinkSerializer):
    people = serializers.SerializerMethodField(help_text="Newest first, at most 100.")

    class Meta(JoinLinkSerializer.Meta):
        fields = (*JoinLinkSerializer.Meta.fields, "people")
        read_only_fields = fields

    @extend_schema_field(JoinLinkPersonSerializer(many=True))
    def get_people(self, link: JoinLink) -> list[dict]:
        people = (
            Membership.objects.filter(join_link=link)
            .select_related("user", "position")
            .order_by(Coalesce("onboarded_at", "created_at").desc(), "-pk")[:PEOPLE_SHOWN]
        )
        return JoinLinkPersonSerializer(people, many=True).data


class JoinLinkInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    auto_approve = serializers.BooleanField(default=True)
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    role_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Empty: the default role."
    )
    position_id = serializers.IntegerField(required=False, allow_null=True)
    max_uses = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=join_links.MAX_PLACES
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_expires_at(self, value):
        now = timezone.now()
        if value is not None and value <= now:
            raise serializers.ValidationError(_("The end must be in the future."))
        if value is not None and value > now + timedelta(days=join_links.MAX_DAYS):
            raise serializers.ValidationError(_("A link can work for at most a year."))
        return value


class JoinLinkPatchSerializer(JoinLinkInputSerializer):
    name = serializers.CharField(max_length=100, required=False)
    auto_approve = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False, help_text="False stops the link.")


class JoinLinkViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    """Team links: everyone who opens one joins with its branch, role and position."""

    perm = Perm.MEMBERS_APPROVE
    serializer_class = JoinLinkSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return JoinLink.objects.none()
        return join_links.visible_links(self.membership)

    def get_serializer_class(self):
        return JoinLinkDetailSerializer if self.action == "retrieve" else JoinLinkSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context
        return context | {
            "default_role": join_links.default_role(self.company),
            "now": timezone.now(),
        }

    def list(self, request, *args, **kwargs):
        context = self.get_serializer_context()
        links = join_links.ordered(self.get_queryset(), context["now"])
        return Response(JoinLinkSerializer(links, many=True, context=context).data)

    @extend_schema(request=JoinLinkInputSerializer, responses={201: JoinLinkSerializer})
    def create(self, request, company_id):
        serializer = JoinLinkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = join_links.create_link(
            self.company, by=self.membership, **self._fields(serializer.validated_data)
        )
        return Response(self._one(link), status=status.HTTP_201_CREATED)

    @extend_schema(request=JoinLinkPatchSerializer, responses=JoinLinkSerializer)
    def partial_update(self, request, company_id, pk):
        link = self.get_object()
        serializer = JoinLinkPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        link = join_links.update_link(
            link, by=self.membership, **self._fields(serializer.validated_data)
        )
        return Response(self._one(link))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        join_links.delete_link(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _fields(self, data: dict) -> dict:
        """The validated body as the service takes it: rows of this company for the ids."""
        company = self.company
        fields = {
            name: data[name]
            for name in ("name", "auto_approve", "max_uses", "expires_at", "is_active")
            if name in data
        }
        for name, model in (("branch", Branch), ("role", AccessRole), ("position", Position)):
            key = f"{name}_id"
            if key in data:
                value = data[key]
                fields[name] = (
                    get_object_or_404(model.objects.filter(company=company), pk=value)
                    if value is not None
                    else None
                )
        return fields

    def _one(self, link: JoinLink) -> dict:
        fresh = self.get_queryset().filter(pk=link.pk).first() or link
        return JoinLinkSerializer(fresh, context=self.get_serializer_context()).data
