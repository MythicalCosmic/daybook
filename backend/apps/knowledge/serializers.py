"""Shapes of the knowledge base API (owner dashboard and mini app share most of them)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import signed_url
from apps.knowledge import queries, sanitize, targets
from apps.knowledge.models import Page, PageImage, PageLink, PageVersion, Space
from apps.members.models import Membership

IMAGE_TTL = 6 * 60 * 60  # a page stays open for a while; pictures shouldn't break meanwhile


def person(member: Membership | None) -> dict | None:
    if member is None:
        return None
    user = getattr(member, "user", None)
    photo = getattr(user, "photo", None) if user is not None else None
    return {
        "id": member.pk,
        "name": member.full_name or (str(user) if user else f"#{member.pk}"),
        "photo_url": photo.url if photo else None,
    }


class KnowledgePersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class KnowledgeRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class KnowledgeSpaceRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    icon = serializers.CharField()


def space_ref(space: Space) -> dict:
    return {"id": space.pk, "name": space.name, "icon": space.icon}


class KnowledgeSpaceCountsSerializer(serializers.Serializer):
    pages = serializers.IntegerField()
    published = serializers.IntegerField()
    drafts = serializers.IntegerField()


class KnowledgeSpaceSerializer(serializers.ModelSerializer):
    positions = serializers.SerializerMethodField()
    archived = serializers.SerializerMethodField()
    counts = serializers.SerializerMethodField()

    class Meta:
        model = Space
        fields = [
            "id",
            "name",
            "icon",
            "description",
            "audience_all",
            "positions",
            "position",
            "archived",
            "counts",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(KnowledgeRefSerializer(many=True))
    def get_positions(self, space) -> list[dict]:
        return [{"id": p.pk, "name": p.name} for p in space.positions.all()]

    def get_archived(self, space) -> bool:
        return space.archived_at is not None

    @extend_schema_field(KnowledgeSpaceCountsSerializer)
    def get_counts(self, space) -> dict:
        counts = self.context.get("counts", {})
        return counts.get(space.pk, {"pages": 0, "published": 0, "drafts": 0})


class KnowledgeSpaceWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    icon = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    description = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )
    audience_all = serializers.BooleanField(required=False, default=True)
    position_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


class KnowledgeSpaceUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    icon = serializers.CharField(max_length=16, required=False, allow_blank=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    audience_all = serializers.BooleanField(required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class KnowledgeReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), max_length=500)


class KnowledgeTreeNodeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()
    published = serializers.BooleanField()
    require_ack = serializers.BooleanField()
    position = serializers.IntegerField()
    children = serializers.ListField(child=serializers.DictField())


def tree_json(nodes: list[queries.TreeNode]) -> list[dict]:
    return [
        {
            "id": node.page.pk,
            "title": node.page.title,
            "emoji": node.page.emoji,
            "published": node.page.published,
            "require_ack": node.page.require_ack,
            "position": node.page.position,
            "children": tree_json(node.children),
        }
        for node in nodes
    ]


class KnowledgeReadCountSerializer(serializers.Serializer):
    read = serializers.IntegerField()
    total = serializers.IntegerField()


class KnowledgePageRowSerializer(serializers.ModelSerializer):
    """A page in lists and search results."""

    space = serializers.SerializerMethodField()
    updated_by = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()
    read = serializers.SerializerMethodField()
    archived = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            "id",
            "title",
            "emoji",
            "space",
            "parent_id",
            "published",
            "published_at",
            "require_ack",
            "version",
            "archived",
            "updated_at",
            "updated_by",
            "excerpt",
            "read",
        ]

    @extend_schema_field(KnowledgeSpaceRefSerializer)
    def get_space(self, page) -> dict:
        return space_ref(page.space)

    @extend_schema_field(KnowledgePersonSerializer(allow_null=True))
    def get_updated_by(self, page) -> dict | None:
        return person(page.updated_by)

    def get_excerpt(self, page) -> str:
        return sanitize.excerpt(page.body_text, 160)

    def get_archived(self, page) -> bool:
        return page.archived_at is not None

    @extend_schema_field(KnowledgeReadCountSerializer(allow_null=True))
    def get_read(self, page) -> dict | None:
        counts = self.context.get("read_counts")
        if counts is None or page.pk not in counts:
            return None
        read, total = counts[page.pk]
        return {"read": read, "total": total}


class KnowledgeLinkSerializer(serializers.ModelSerializer):
    page = serializers.SerializerMethodField()

    class Meta:
        model = PageLink
        fields = ["id", "target_type", "target_id", "target_title", "page", "created_at"]

    @extend_schema_field(
        serializers.DictField(help_text="{id, title, emoji, space: {id, name, icon}}")
    )
    def get_page(self, link) -> dict:
        page = link.page
        return {
            "id": page.pk,
            "title": page.title,
            "emoji": page.emoji,
            "space": space_ref(page.space),
        }


class KnowledgeMyAckSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    at = serializers.DateTimeField()
    current = serializers.BooleanField()


class KnowledgeCrumbSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField()


class KnowledgeChildSerializer(KnowledgeCrumbSerializer):
    published = serializers.BooleanField()


def body_with_images(body: str, *, user, company_id: int) -> str:
    """The page body with a fresh signed link on each of its pictures, for this reader."""
    ids = sanitize.image_ids(body)
    if not ids:
        return body
    images = {
        image.pk: image
        for image in PageImage.objects.filter(company_id=company_id, pk__in=ids).only(
            "pk", "file", "company_id"
        )
    }

    def url_for(image_id: int) -> str | None:
        image = images.get(image_id)
        if image is None or not image.file:
            return None
        return signed_url(
            image.file,
            user=user,
            company_id=company_id,
            check=f"knowledge.image:{image.pk}",
            ttl=IMAGE_TTL,
        )

    return sanitize.with_image_urls(body, url_for)


class KnowledgePageDetailSerializer(KnowledgePageRowSerializer):
    body = serializers.SerializerMethodField()
    breadcrumbs = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()
    links = serializers.SerializerMethodField()
    my_ack = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta(KnowledgePageRowSerializer.Meta):
        fields = [
            *KnowledgePageRowSerializer.Meta.fields,
            "body",
            "ack_version",
            "breadcrumbs",
            "children",
            "links",
            "my_ack",
            "created_at",
            "created_by",
            "can_edit",
        ]

    def get_body(self, page) -> str:
        request = self.context["request"]
        return body_with_images(page.body, user=request.user, company_id=page.company_id)

    @extend_schema_field(KnowledgeCrumbSerializer(many=True))
    def get_breadcrumbs(self, page) -> list[dict]:
        return [
            {"id": crumb.pk, "title": crumb.title, "emoji": crumb.emoji}
            for crumb in queries.ancestors(page)
        ]

    @extend_schema_field(KnowledgeChildSerializer(many=True))
    def get_children(self, page) -> list[dict]:
        member = self.context["membership"]
        pages = queries.reader_pages if self.context.get("reader") else queries.readable_pages
        readable = pages(member).filter(parent=page).order_by("position", "pk")
        return [
            {
                "id": child.pk,
                "title": child.title,
                "emoji": child.emoji,
                "published": child.published,
            }
            for child in readable
        ]

    @extend_schema_field(KnowledgeLinkSerializer(many=True))
    def get_links(self, page) -> list[dict]:
        links = page.links.select_related("page", "page__space").order_by("pk")
        visible = targets.visible_links(self.context["membership"], links)
        return KnowledgeLinkSerializer(visible, many=True).data

    @extend_schema_field(KnowledgeMyAckSerializer(allow_null=True))
    def get_my_ack(self, page) -> dict | None:
        ack = queries.my_ack(self.context["membership"], page)
        if ack is None:
            return None
        return {"version": ack.version, "at": ack.at, "current": queries.is_read(ack.version, page)}

    @extend_schema_field(KnowledgePersonSerializer(allow_null=True))
    def get_created_by(self, page) -> dict | None:
        return person(page.created_by)

    def get_can_edit(self, page) -> bool:
        return not self.context.get("reader") and queries.can_manage(self.context["membership"])


class KnowledgePageCreateSerializer(serializers.Serializer):
    space = serializers.IntegerField()
    parent = serializers.IntegerField(required=False, allow_null=True, default=None)
    title = serializers.CharField(max_length=200)
    emoji = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    body = serializers.CharField(
        required=False, allow_blank=True, default="", trim_whitespace=False
    )
    require_ack = serializers.BooleanField(required=False, default=False)
    publish = serializers.BooleanField(required=False, default=False)
    notify = serializers.BooleanField(required=False, default=True)


class KnowledgePageSaveSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    emoji = serializers.CharField(max_length=16, required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    require_ack = serializers.BooleanField(required=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    base_version = serializers.IntegerField(required=False, allow_null=True, default=None)
    reread = serializers.BooleanField(required=False, default=False)
    notify = serializers.BooleanField(required=False, default=True)


class KnowledgePublishSerializer(serializers.Serializer):
    notify = serializers.BooleanField(required=False, default=True)


class KnowledgeMoveSerializer(serializers.Serializer):
    space = serializers.IntegerField(required=False, allow_null=True, default=None)
    parent = serializers.IntegerField(required=False, allow_null=True, default=None)
    index = serializers.IntegerField(min_value=0)


class KnowledgeVersionSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    current = serializers.SerializerMethodField()

    class Meta:
        model = PageVersion
        fields = ["version", "title", "emoji", "note", "created_by", "created_at", "current"]

    @extend_schema_field(KnowledgePersonSerializer(allow_null=True))
    def get_created_by(self, version) -> dict | None:
        return person(version.created_by)

    def get_current(self, version) -> bool:
        return version.version == self.context.get("current_version")


class KnowledgeVersionDetailSerializer(KnowledgeVersionSerializer):
    body = serializers.SerializerMethodField()

    class Meta(KnowledgeVersionSerializer.Meta):
        fields = [*KnowledgeVersionSerializer.Meta.fields, "body"]

    def get_body(self, version) -> str:
        request = self.context["request"]
        return body_with_images(version.body, user=request.user, company_id=version.company_id)


class KnowledgeReaderSerializer(serializers.Serializer):
    member = serializers.SerializerMethodField()
    status = serializers.ChoiceField(choices=["read", "outdated", "unread"])
    version = serializers.IntegerField(allow_null=True)
    at = serializers.DateTimeField(allow_null=True)

    @extend_schema_field(serializers.DictField(help_text="{id, name, photo_url, position, branch}"))
    def get_member(self, row) -> dict:
        member = row.membership
        return person(member) | {
            "position": member.position.name if member.position else None,
            "branch": member.home_branch.name if member.home_branch else None,
        }


class KnowledgeLinkCreateSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=PageLink.Target.choices)
    target_id = serializers.IntegerField(min_value=1)


class KnowledgeTargetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=PageLink.Target.choices)
    id = serializers.IntegerField()
    title = serializers.CharField()
    subtitle = serializers.CharField()


class KnowledgeImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False, use_url=False)
    page = serializers.IntegerField(required=False, allow_null=True, default=None)


class KnowledgeImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()


class KnowledgeSettingsSerializer(serializers.Serializer):
    notify_on_publish = serializers.BooleanField()
    remind_unread_after_hours = serializers.IntegerField(min_value=0, max_value=720)
