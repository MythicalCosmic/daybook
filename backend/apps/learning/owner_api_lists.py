"""Owner endpoints of the unchangeable lists ("O‘zgarmas ro‘yxat", `apps.learning.study_lists`),
routed by `owner_urls_lists.py` under `/api/v1/owner/companies/<id>/learning/lists/…`:

    lists/ (+ {id}/)                     lists (`?state=open|sealed`, `?q=`, `?branch=`); create,
                                         change while open, delete while it has no line
    lists/{id}/topics/ (+ {tid}/)        add topics; rename or remove one no line mentions yet
    lists/{id}/students/ (+ {sid}/)      add staff or typed-in names; change or remove one unused
    lists/{id}/candidates/?q=            staff who could be added
    lists/{id}/marks/                    write a line ("studied")
    lists/{id}/marks/{mid}/correct/      take a line back, with the reason
    lists/{id}/seal/                     seal the list: final

Reading needs `learning.view` (or `learning.manage`), every change `learning.manage`. A list of a
branch outside the caller's branches answers 404; everything answers 404 while the module is off.
Every change answers the whole list.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import OwnerViewSet
from apps.learning import queries, study_lists
from apps.learning.models import StudyList
from apps.learning.owner_api_courses import BRANCH, MANAGE, READ, LearningOn, Scope
from apps.learning.serializers_lists import (
    LearningStudyCandidateSerializer,
    LearningStudyCorrectSerializer,
    LearningStudyListRowSerializer,
    LearningStudyListSerializer,
    LearningStudyListWriteSerializer,
    LearningStudyMarkWriteSerializer,
    LearningStudyStudentsSerializer,
    LearningStudyStudentWriteSerializer,
    LearningStudyTopicsSerializer,
    LearningStudyTopicWriteSerializer,
)

WRITES = (
    "create",
    "partial_update",
    "destroy",
    "topics",
    "topic",
    "candidates",
    "students",
    "student",
    "marks",
    "correct",
    "seal",
)


def _valid(serializer_class, data, *, partial: bool = False) -> dict:
    serializer = serializer_class(data=data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class StudyListViewSet(LearningOn, Scope, OwnerViewSet):
    """Unchangeable lists: the register, its topics and students, its lines and the seal."""

    lookup_value_regex = r"\d+"
    pagination_class = None  # the index and the candidates are plain arrays
    perm = READ
    perms_by_action = dict.fromkeys(WRITES, MANAGE)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StudyList.objects.none()
        return study_lists.visible(self.company, self.branch_scope)

    def study_list(self, pk) -> StudyList:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def answer(self, study_list: StudyList, code: int = status.HTTP_200_OK) -> Response:
        return Response(study_lists.detail(study_list), status=code)

    def branch(self, branch_id: int | None) -> Branch | None:
        """A branch of the company in the caller's scope (None: the whole company)."""
        if branch_id is None:
            return None
        allowed = self.branch_scope
        found = Branch.objects.filter(company=self.company, pk=branch_id).first()
        if found is None or (allowed is not None and found.pk not in allowed):
            raise ValidationError({"branch_id": [_("Pick one of your branches.")]})
        return found

    # The lists ------------------------------------------------------------------------------

    @extend_schema(
        parameters=[
            OpenApiParameter("state", str, enum=["open", "sealed"]),
            OpenApiParameter("q", str),
            BRANCH,
        ],
        responses=LearningStudyListRowSerializer(many=True),
    )
    def list(self, request, company_id):
        lists = self.get_queryset()
        state = request.query_params.get("state")
        if state in StudyList.State.values:
            lists = lists.filter(state=state)
        q = (request.query_params.get("q") or "").strip()
        if q:
            lists = lists.filter(Q(title__icontains=q) | Q(teacher__icontains=q))
        if request.query_params.get("branch"):
            lists = lists.filter(branch_id__in=self.branches())
        return Response(study_lists.rows(lists))

    @extend_schema(
        request=LearningStudyListWriteSerializer, responses={201: LearningStudyListSerializer}
    )
    def create(self, request, company_id):
        data = _valid(LearningStudyListWriteSerializer, request.data)
        created = study_lists.create_list(
            self.company,
            by=self.membership,
            title=data["title"],
            description=data.get("description", ""),
            teacher=data.get("teacher", ""),
            branch=self.branch(data.get("branch_id")),
        )
        return self.answer(created, status.HTTP_201_CREATED)

    @extend_schema(responses=LearningStudyListSerializer)
    def retrieve(self, request, company_id, pk=None):
        return self.answer(self.study_list(pk))

    @extend_schema(request=LearningStudyListWriteSerializer, responses=LearningStudyListSerializer)
    def partial_update(self, request, company_id, pk=None):
        found = self.study_list(pk)
        data = _valid(LearningStudyListWriteSerializer, request.data, partial=True)
        changes = {key: data[key] for key in ("title", "description", "teacher") if key in data}
        if "branch_id" in data:
            changes["branch"] = self.branch(data["branch_id"])
        study_lists.update_list(found, by=self.membership, **changes)
        return self.answer(found)

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk=None):
        study_lists.delete_list(self.study_list(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["post"])
    def seal(self, request, company_id, pk=None):
        found = self.study_list(pk)
        study_lists.seal(found, by=self.membership)
        return self.answer(found)

    # Topics -------------------------------------------------------------------------------

    @extend_schema(request=LearningStudyTopicsSerializer, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["post"])
    def topics(self, request, company_id, pk=None):
        found = self.study_list(pk)
        data = _valid(LearningStudyTopicsSerializer, request.data)
        study_lists.add_topics(found, by=self.membership, titles=data["titles"])
        return self.answer(found)

    @extend_schema(
        methods=["PATCH"],
        request=LearningStudyTopicWriteSerializer,
        responses=LearningStudyListSerializer,
    )
    @extend_schema(methods=["DELETE"], request=None, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"topics/(?P<topic_id>\d+)")
    def topic(self, request, company_id, pk=None, topic_id=None):
        found = self.study_list(pk)
        if request.method == "DELETE":
            study_lists.remove_topic(found, by=self.membership, topic_id=int(topic_id))
        else:
            data = _valid(LearningStudyTopicWriteSerializer, request.data)
            study_lists.rename_topic(
                found, by=self.membership, topic_id=int(topic_id), title=data["title"]
            )
        return self.answer(found)

    # Students -----------------------------------------------------------------------------

    @extend_schema(
        parameters=[OpenApiParameter("q", str)],
        responses=LearningStudyCandidateSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def candidates(self, request, company_id, pk=None):
        found = self.study_list(pk)
        on_list = found.students.exclude(membership=None).values_list("membership_id", flat=True)
        people = queries.people_in_scope(self.company, branch_ids=self.branch_scope).exclude(
            pk__in=on_list
        )
        q = (request.query_params.get("q") or "").strip()
        if q:
            people = people.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))
        return Response(
            [
                {
                    "id": person.pk,
                    "name": study_lists.member_name(person),
                    "position": person.position.name if person.position_id else None,
                    "branch": person.home_branch.name if person.home_branch_id else None,
                }
                for person in people.order_by("first_name", "last_name", "pk")[:50]
            ]
        )

    @extend_schema(request=LearningStudyStudentsSerializer, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["post"])
    def students(self, request, company_id, pk=None):
        found = self.study_list(pk)
        data = _valid(LearningStudyStudentsSerializer, request.data)
        member_ids = data.get("member_ids") or []
        study_lists.add_students(
            found,
            by=self.membership,
            members=self.scoped_people(member_ids) if member_ids else [],
            names=[(row["name"], row.get("note", "")) for row in data.get("names") or []],
        )
        return self.answer(found)

    @extend_schema(
        methods=["PATCH"],
        request=LearningStudyStudentWriteSerializer,
        responses=LearningStudyListSerializer,
    )
    @extend_schema(methods=["DELETE"], request=None, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"students/(?P<student_id>\d+)")
    def student(self, request, company_id, pk=None, student_id=None):
        found = self.study_list(pk)
        if request.method == "DELETE":
            study_lists.remove_student(found, by=self.membership, student_id=int(student_id))
        else:
            data = _valid(LearningStudyStudentWriteSerializer, request.data)
            study_lists.edit_student(found, by=self.membership, student_id=int(student_id), **data)
        return self.answer(found)

    # Lines --------------------------------------------------------------------------------

    @extend_schema(request=LearningStudyMarkWriteSerializer, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["post"])
    def marks(self, request, company_id, pk=None):
        found = self.study_list(pk)
        data = _valid(LearningStudyMarkWriteSerializer, request.data)
        study_lists.write_mark(
            found,
            by=self.membership,
            topic_id=data["topic_id"],
            student_id=data["student_id"],
            studied_on=data.get("studied_on"),
            note=data.get("note", ""),
        )
        return self.answer(found)

    @extend_schema(request=LearningStudyCorrectSerializer, responses=LearningStudyListSerializer)
    @action(detail=True, methods=["post"], url_path=r"marks/(?P<mark_id>\d+)/correct")
    def correct(self, request, company_id, pk=None, mark_id=None):
        found = self.study_list(pk)
        data = _valid(LearningStudyCorrectSerializer, request.data)
        study_lists.correct_mark(
            found, by=self.membership, mark_id=int(mark_id), reason=data["reason"]
        )
        return self.answer(found)
