"""The job titles (positions) a new company starts with: a pharmacy's usual staff, in the
company's language, each with the default role that comes with it (DEFAULT_TITLE_ROLES; the
others give the company's default role). Owners rename, reorder or remove them, and change the
access each one gives, in People, Positions."""

from apps.members.models import AccessRole, Position

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
# The access a default title gives, by the English names of DEFAULT_POSITIONS and DEFAULT_ROLES.
# Never the Owner role; a department head's rights come from heading a department.
DEFAULT_TITLE_ROLES = {
    "Top manager": "Manager",
    "Manager": "Manager",
    "Senior pharmacist": "Pharmacist",
    "Pharmacist": "Pharmacist",
    "Cashier": "Cashier",
    "Accountant": "Accountant",
}


def default_names(language: str) -> list[str]:
    column = LANGUAGES.index(language) if language in LANGUAGES else LANGUAGES.index("uz")
    return [names[column] for names in DEFAULT_POSITIONS]


def create_default_positions(company) -> int:
    """The usual job titles, for a company that has none yet, each giving its default role
    when the company has a role of that name. Returns how many were made."""
    if Position.objects.filter(company=company).exists():
        return 0
    roles = {
        role.name: role
        for role in AccessRole.objects.filter(
            company=company, is_owner=False, name__in=set(DEFAULT_TITLE_ROLES.values())
        )
    }
    Position.objects.bulk_create(
        Position(
            company=company,
            name=name,
            order=index,
            role=roles.get(DEFAULT_TITLE_ROLES.get(DEFAULT_POSITIONS[index][0], "")),
        )
        for index, name in enumerate(default_names(company.default_language))
    )
    return len(DEFAULT_POSITIONS)
