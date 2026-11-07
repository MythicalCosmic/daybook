"""What a company starts with when it switches the stock module on: the settings row and a
pharmacy category tree (two levels), named in the company's language. Owners rename, add and
delete freely; nothing is made while the module is off."""

from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.inventory import conf
from apps.inventory.models import ProductCategory

# (key, name, parent key)
CATEGORIES = (
    ("medicines", _("Medicines"), None),
    ("antibiotics", _("Antibiotics and antivirals"), "medicines"),
    ("pain", _("Pain and fever"), "medicines"),
    ("heart", _("Heart and blood pressure"), "medicines"),
    ("stomach", _("Stomach and digestion"), "medicines"),
    ("allergy", _("Allergy"), "medicines"),
    ("cold", _("Cough and cold"), "medicines"),
    ("hormones", _("Hormones and diabetes"), "medicines"),
    ("nervous", _("Nervous system"), "medicines"),
    ("vitamins", _("Vitamins and supplements"), None),
    ("devices", _("Medical devices"), None),
    ("hygiene", _("Hygiene and baby care"), None),
)


def ensure(company) -> None:
    """The settings row and the missing categories. Idempotent: it runs when the module is
    switched on and after every deploy (`ensure_company_defaults`)."""
    if not company.has_feature("stock"):
        return
    conf.get_settings(company)
    categories(company)


def categories(company) -> dict[str, ProductCategory]:
    """The default tree by key, made where missing (a category is found again by its name in
    the company's language)."""
    found: dict[str, ProductCategory] = {}
    with translation.override(company.default_language):
        existing = {row.name: row for row in ProductCategory.objects.for_company(company)}
        for order, (key, name, parent) in enumerate(CATEGORIES):
            name = str(name)
            row = existing.get(name)
            if row is None:
                row = ProductCategory.objects.create(
                    company=company,
                    name=name,
                    parent=found.get(parent) if parent else None,
                    order=order,
                )
                existing[name] = row
            found[key] = row
    return found
