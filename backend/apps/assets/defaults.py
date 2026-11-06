"""What a company starts with when it switches the assets module on: the policy row and the
categories a pharmacy needs, each with its useful life, method, the Tax Code group and rate
(Tax Code art. 306: the annual maximum rates; buxgalter.uz, 25.09.2025), the months between
services and between official instrument checks. Owners rename and change them freely; the
legal numbers are to be confirmed by the company's accountant."""

from django.db import IntegrityError, transaction
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.assets import conf
from apps.assets.models import AssetCategory, Method

FIXED, INTANGIBLE, LOW = (
    AssetCategory.Kind.FIXED,
    AssetCategory.Kind.INTANGIBLE,
    AssetCategory.Kind.LOW_VALUE,
)
SL, NONE = Method.STRAIGHT_LINE, Method.NONE

# Tax Code art. 306, the annual maximum depreciation rates by group (percent a year).
TAX_GROUPS = {
    "I-1": ("5.00", _("I.1 Buildings")),
    "I-2": ("10.00", _("I.2 Structures")),
    "II": ("15.00", _("II Pipelines, power and communication lines")),
    "III": ("20.00", _("III Machinery and equipment")),
    "IV-1": ("10.00", _("IV.1 Aircraft, ships, railway rolling stock")),
    "IV-2": ("20.00", _("IV.2 Cars, trailers and other transport")),
    "V": ("40.00", _("V Computers and peripherals")),
    "VI": ("15.00", _("VI Everything else that depreciates")),
}

# (code, kind, name, life months, method, salvage %, tax group, service months, verify months, icon)
CATEGORIES = (
    ("fridges", FIXED, _("Pharmacy fridges"), 84, SL, 0, "III", 6, None, "refrigerator"),
    ("climate", FIXED, _("Air conditioners"), 84, SL, 0, "III", 12, None, "air-vent"),
    (
        "furniture",
        FIXED,
        _("Shelves, counters and furniture"),
        120,
        SL,
        0,
        "VI",
        None,
        None,
        "armchair",
    ),
    (
        "computers",
        FIXED,
        _("Computers and office equipment"),
        48,
        SL,
        0,
        "V",
        None,
        None,
        "monitor",
    ),
    (
        "tills",
        FIXED,
        _("Cash registers, terminals and scanners"),
        60,
        SL,
        0,
        "III",
        12,
        None,
        "scan-barcode",
    ),
    (
        "instruments",
        FIXED,
        _("Thermometers, hygrometers and scales"),
        36,
        SL,
        0,
        "III",
        None,
        12,
        "thermometer",
    ),
    ("security", FIXED, _("Cameras, alarms and safes"), 60, SL, 0, "III", 12, None, "cctv"),
    ("vehicles", FIXED, _("Vehicles"), 72, SL, 10, "IV-2", 6, None, "car"),
    (
        "renovation",
        FIXED,
        _("Renovation of rented premises"),
        60,
        SL,
        0,
        "VI",
        None,
        None,
        "paint-roller",
    ),
    ("buildings", FIXED, _("Buildings"), 240, SL, 0, "I-1", None, None, "building-2"),
    ("software", INTANGIBLE, _("Software and licences"), 36, SL, 0, "", None, None, "app-window"),
    (
        "low_value",
        LOW,
        _("Low-value items: uniforms, keys, small tools"),
        None,
        NONE,
        0,
        "",
        None,
        None,
        "key-round",
    ),
)


def ensure(company) -> None:
    """The policy row and the missing categories, in the company's language. Idempotent: it runs
    when the module is switched on and after every deploy (`ensure_company_defaults`)."""
    if not company.has_feature("assets"):
        return
    conf.get_settings(company)
    with translation.override(company.default_language):
        have = set(
            AssetCategory.objects.filter(company=company)
            .exclude(system_code="")
            .values_list("system_code", flat=True)
        )
        names = set(AssetCategory.objects.filter(company=company).values_list("name", flat=True))
        for order, row in enumerate(CATEGORIES):
            code, kind, name, life, method, salvage, group, service, verify, icon = row
            name = str(name)
            if code in have or name in names:
                continue
            rate = TAX_GROUPS[group][0] if group else None
            try:
                with transaction.atomic():
                    AssetCategory.objects.create(
                        company=company,
                        system_code=code,
                        kind=kind,
                        name=name,
                        life_months=life,
                        method=method,
                        salvage_percent=salvage,
                        tax_group=group,
                        tax_rate=rate,
                        service_months=service,
                        verify_months=verify,
                        icon=icon,
                        order=order,
                    )
            except IntegrityError:
                pass  # a concurrent ensure made it
    if company.has_feature("finance"):
        from apps.finance import defaults as finance_defaults

        finance_defaults.ensure_asset_categories(company)
