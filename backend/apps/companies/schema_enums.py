"""drf-spectacular enum names of company setup, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: import strings only.
"""

ENUM_NAME_OVERRIDES = {
    # The module switches (`Company.features`).
    "CompaniesFeatureEnum": "apps.companies.models.Feature",
}
