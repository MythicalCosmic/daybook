"""factory_boy factories for the models of HR records."""

import factory
from factory.django import DjangoModelFactory

from apps.hr.models import DocumentKind, EmployeeDocument, EmployeeProfile, RequiredDocument


class EmployeeProfileFactory(DjangoModelFactory):
    class Meta:
        model = EmployeeProfile
        django_get_or_create = ("membership",)

    membership = None
    company = factory.LazyAttribute(lambda profile: profile.membership.company)


class EmployeeDocumentFactory(DjangoModelFactory):
    class Meta:
        model = EmployeeDocument

    membership = None
    company = factory.LazyAttribute(lambda document: document.membership.company)
    kind = DocumentKind.MEDICAL_BOOK


class RequiredDocumentFactory(DjangoModelFactory):
    class Meta:
        model = RequiredDocument

    kind = DocumentKind.MEDICAL_BOOK
