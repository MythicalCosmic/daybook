"""What switching Ko‘z on makes (`apps.companies.services.FEATURE_APPS`): its settings row, with
the defaults of docs/KOZ.md §6.7. Boxes and cameras come from the owner and the boxes."""

from apps.vision import conf


def ensure(company) -> None:
    conf.get_settings(company)
