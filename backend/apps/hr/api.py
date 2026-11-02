"""Employee (mini app) endpoints of HR records; routed in `urls.py` under
`/api/v1/companies/<id>/hr/…` (docs/PLAN-OWNER.md §4.10, prefix E).

Everything is the signed-in person's own file: no permission needed. A suspended person may
still read it (not change it). While the HR module is off the endpoints answer 403.

    GET/PATCH   hr/profile/                          phone, email, address, birthday shown, card
    GET/POST    hr/profile/emergency-contacts/       ·  PATCH/DELETE …/{id}/
    GET/POST    hr/documents/                        their documents; upload a renewed one
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hr import conf, queries, services
from apps.hr import serializers as s
from apps.hr.models import EmergencyContact, EmployeeDocument
from apps.members.api import IsCompanyMember
from apps.members.models import Membership


class HROn(BasePermission):
    """After IsCompanyMember: the module must be switched on."""

    def has_permission(self, request, view):
        if not view.membership.company.has_feature("hr"):
            raise PermissionDenied(_("HR isn't switched on for this company."))
        return True


class MemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, HROn)
    # Their own file stays readable while their access is paused (§13.4).
    allow_suspended = True
    membership: Membership

    def context(self) -> dict:
        company = self.membership.company
        return {
            "request": self.request,
            "membership": self.membership,
            "today": queries.today(company),
            "warn_days": conf.get_settings(company).document_warn_days,
        }


class MyProfileView(MemberView):
    """My details, IDs and card masked back."""

    @extend_schema(responses=s.MyProfileSerializer)
    def get(self, request, company_id):
        profile = queries.profile_of(self.membership)
        return Response(s.MyProfileSerializer(profile, context=self.context()).data)

    @extend_schema(request=s.MyProfileUpdateSerializer, responses=s.MyProfileSerializer)
    def patch(self, request, company_id):
        serializer = s.MyProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = services.update_own_profile(self.membership, **serializer.validated_data)
        return Response(s.MyProfileSerializer(profile, context=self.context()).data)


class MyContactsView(MemberView):
    """Whom to call when something happens to me (three at most)."""

    @extend_schema(responses=s.EmergencyContactSerializer(many=True))
    def get(self, request, company_id):
        rows = EmergencyContact.objects.filter(profile__membership=self.membership)
        return Response(s.EmergencyContactSerializer(rows, many=True).data)

    @extend_schema(
        request=s.EmergencyContactSerializer, responses={201: s.EmergencyContactSerializer}
    )
    def post(self, request, company_id):
        serializer = s.EmergencyContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact = services.add_contact(
            self.membership, by=self.membership, **serializer.validated_data
        )
        return Response(s.EmergencyContactSerializer(contact).data, status=status.HTTP_201_CREATED)


class MyContactView(MemberView):
    def contact(self, pk) -> EmergencyContact:
        contact = (
            EmergencyContact.objects.filter(profile__membership=self.membership, pk=pk)
            .select_related("profile__membership__company")
            .first()
        )
        if contact is None:
            raise NotFound
        return contact

    @extend_schema(request=s.EmergencyContactSerializer, responses=s.EmergencyContactSerializer)
    def patch(self, request, company_id, pk):
        contact = self.contact(pk)
        serializer = s.EmergencyContactSerializer(contact, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        contact = services.update_contact(contact, by=self.membership, **serializer.validated_data)
        return Response(s.EmergencyContactSerializer(contact).data)

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk):
        services.remove_contact(self.contact(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyDocumentsView(MemberView):
    """My documents (those HR shows me), and uploading one: a renewed medical book, a new
    certificate. HR checks it afterwards."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    @extend_schema(responses=s.MyDocumentSerializer(many=True))
    def get(self, request, company_id):
        rows = EmployeeDocument.objects.filter(
            membership=self.membership, visible_to_employee=True
        ).order_by("kind", "-expires_on", "-pk")
        return Response(s.MyDocumentSerializer(rows, many=True, context=self.context()).data)

    @extend_schema(request=s.MyDocumentWriteSerializer, responses={201: s.MyDocumentSerializer})
    def post(self, request, company_id):
        serializer = s.MyDocumentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        document = services.add_document(
            self.membership, by=self.membership, kind=data.pop("kind"), **data
        )
        return Response(
            s.MyDocumentSerializer(document, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )
