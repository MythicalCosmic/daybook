import factory
from factory.django import DjangoModelFactory

from apps.companies.models import Company
from apps.companies.services import create_company


class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f"Company {n}")
    slug = factory.Sequence(lambda n: f"company-{n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Go through the service so every test company gets its default roles.
        return create_company(**kwargs)
