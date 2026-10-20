import factory
from factory.django import DjangoModelFactory

from apps.companies.models import Branch, Company
from apps.companies.services import create_company


class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f"Company {n}")
    slug = factory.Sequence(lambda n: f"company-{n}")
    # Tests read English; the translation tests pick other languages on purpose.
    default_language = "en"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Go through the service so every test company is set up like a real one: default
        # roles, reminder policy and its first branch. Other fields are set afterwards.
        company = create_company(
            name=kwargs.pop("name"),
            slug=kwargs.pop("slug"),
            timezone=kwargs.pop("timezone", "Asia/Tashkent"),
            language=kwargs.pop("default_language"),
            base_currency=kwargs.pop("base_currency", "UZS"),
        )
        if kwargs:
            for field, value in kwargs.items():
                setattr(company, field, value)
            company.save()
        return company


class BranchFactory(DjangoModelFactory):
    class Meta:
        model = Branch

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Branch {n}")
