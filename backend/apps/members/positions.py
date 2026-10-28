"""The job titles (positions) a new company starts with: a pharmacy's usual staff, in the
company's language. Owners rename, reorder or remove them in People, Positions; they grant
nothing (access comes from roles)."""

from apps.members.models import Position

# (English, Uzbek, Russian), in the order people pick from.
DEFAULT_POSITIONS = (
    ("Top manager", "Bosh menejer", "Топ-менеджер"),
    ("Manager", "Menejer", "Менеджер"),
    ("Department head", "Bo‘lim boshlig‘i", "Руководитель отдела"),
    ("Head of pharmacy", "Dorixona mudiri", "Заведующий аптекой"),
    ("Senior pharmacist", "Provizor", "Провизор"),
    ("Pharmacist", "Farmatsevt", "Фармацевт"),
    ("Cashier", "Kassir", "Кассир"),
    ("Stock manager", "Ombor mudiri", "Заведующий складом"),
    ("Stock worker", "Ombor xodimi", "Работник склада"),
    ("Courier", "Kuryer", "Курьер"),
    ("Accountant", "Buxgalter", "Бухгалтер"),
    ("Cleaner", "Farrosh", "Уборщик"),
)
LANGUAGES = ("en", "uz", "ru")


def default_names(language: str) -> list[str]:
    column = LANGUAGES.index(language) if language in LANGUAGES else LANGUAGES.index("uz")
    return [names[column] for names in DEFAULT_POSITIONS]


def create_default_positions(company) -> int:
    """The usual job titles, for a company that has none yet. Returns how many were made."""
    if Position.objects.filter(company=company).exists():
        return 0
    Position.objects.bulk_create(
        Position(company=company, name=name, order=index)
        for index, name in enumerate(default_names(company.default_language))
    )
    return len(DEFAULT_POSITIONS)
