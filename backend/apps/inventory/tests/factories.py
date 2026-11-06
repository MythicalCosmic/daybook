"""factory_boy factories for the models of stock (W2.a, docs/PLAN-OWNER.md §14.5).

Stock itself (what a branch holds of a batch) has no factory on purpose: J1 moves it only
through `apps.inventory.services`, under row locks.
"""

from datetime import date, timedelta
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.inventory.models import Manufacturer, Product, ProductCategory, StockBatch


class ManufacturerFactory(DjangoModelFactory):
    class Meta:
        model = Manufacturer

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Farm Zavod {n}")
    country = "UZ"


class ProductCategoryFactory(DjangoModelFactory):
    class Meta:
        model = ProductCategory

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Category {n}")


class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Paratsetamol {n} mg tabletka №20")
    inn = "paracetamol"
    kind = Product.Kind.MEDICINE
    dosage_form = Product.DosageForm.TABLET
    strength = "500 mg"
    units_per_pack = 2
    part_label = "blister"
    barcode = factory.Sequence(lambda n: f"478{n:010d}")
    sale_price = Decimal("12900.00")


class StockBatchFactory(DjangoModelFactory):
    class Meta:
        model = StockBatch

    company = factory.SelfAttribute("product.company")
    product = factory.SubFactory(ProductFactory)
    series = factory.Sequence(lambda n: f"{230400 + n}")
    expires_on = factory.LazyFunction(lambda: date.today() + timedelta(days=540))
    unit_cost = Decimal("10340.00")
    retail_price = Decimal("12900.00")
