"""Shapes of Davomat's owner API (docs/DAVOMAT.md §1). Times are UTC ISO strings, dates
company-local `YYYY-MM-DD`."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import Language
from apps.davomat import queries
from apps.davomat.models import DavomatSettings

LANGUAGES = tuple(Language.values)


@extend_schema_field({"type": "string", "enum": list(Language.values)})
class LanguageCodeField(serializers.ChoiceField):
    """A language code, described inline: another component for the choices `me.language`
    names (LanguageEnum) would make the schema warn (as companies' DefaultLanguageField)."""

    def __init__(self, **kwargs):
        super().__init__(Language.choices, **kwargs)


class NamedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "DavomatNamed"


# Edition and first run ------------------------------------------------------------------------


class OrganizationSerializer(serializers.Serializer):
    name = serializers.CharField()
    logo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "DavomatOrganization"


class EditionTelegramSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    bot_username = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "DavomatEditionTelegram"


class EditionSerializer(serializers.Serializer):
    edition = serializers.ChoiceField(["davomat", "daybook"])
    product = serializers.CharField(help_text='"Davomat", or the name set in Settings.')
    organization = OrganizationSerializer(allow_null=True)
    needs_setup = serializers.BooleanField(help_text="No organization yet: show the setup.")
    default_language = LanguageCodeField()
    languages = serializers.ListField(
        child=serializers.CharField(), help_text='The languages offered: ["uz", "ru", "en"].'
    )
    telegram = EditionTelegramSerializer()

    class Meta:
        ref_name = "DavomatEdition"


class SetupAdminSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)

    class Meta:
        ref_name = "DavomatSetupAdmin"


class SetupSerializer(serializers.Serializer):
    organization = serializers.CharField(max_length=200)
    timezone = serializers.CharField(max_length=64, default="Asia/Tashkent")
    language = serializers.ChoiceField(Language.choices, default=Language.UZ)
    admin = SetupAdminSerializer()

    class Meta:
        ref_name = "DavomatSetup"


# Passwords ------------------------------------------------------------------------------------


class PasswordLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)

    class Meta:
        ref_name = "DavomatPasswordLogin"


class PasswordChangeSerializer(serializers.Serializer):
    current = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Not needed by someone who never had a password.",
    )
    new = serializers.CharField(max_length=128, trim_whitespace=False)

    class Meta:
        ref_name = "DavomatPasswordChange"


class PasswordSetSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False)

    class Meta:
        ref_name = "DavomatPasswordSet"


# Users ----------------------------------------------------------------------------------------


class RoleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(queries.WEB_KINDS)

    class Meta:
        ref_name = "DavomatRole"


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The membership id.")
    username = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role = RoleSerializer(allow_null=True)
    branch_ids = serializers.ListField(child=serializers.IntegerField())
    is_active = serializers.BooleanField(help_text="May sign in.")
    last_login = serializers.DateTimeField(allow_null=True)
    telegram_linked = serializers.BooleanField()
    is_employee = serializers.BooleanField(help_text="Scans at the terminals too.")
    is_self = serializers.BooleanField(help_text="The user asking.")

    class Meta:
        ref_name = "DavomatUser"


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    role_id = serializers.IntegerField(required=False, help_text="A role of `users/roles/`.")
    role = serializers.ChoiceField(
        queries.WEB_KINDS, required=False, help_text="Or the role's kind instead of its id."
    )
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    employee_id = serializers.IntegerField(
        required=False, help_text="Give this employee a sign-in instead of adding someone."
    )

    class Meta:
        ref_name = "DavomatUserCreate"


class UserUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False)
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    role_id = serializers.IntegerField(required=False)
    role = serializers.ChoiceField(queries.WEB_KINDS, required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    is_active = serializers.BooleanField(required=False)
    is_employee = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "DavomatUserUpdate"


# Employees ------------------------------------------------------------------------------------


class TodaySerializer(serializers.Serializer):
    state = serializers.ChoiceField(queries.TODAY_STATES)
    since = serializers.DateTimeField(allow_null=True)

    class Meta:
        ref_name = "DavomatToday"


class EmployeeSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The membership id.")
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    phone = serializers.CharField()
    position = NamedSerializer(allow_null=True)
    department = NamedSerializer(allow_null=True)
    branch_ids = serializers.ListField(child=serializers.IntegerField())
    face_numbers = serializers.ListField(child=serializers.CharField())
    status = serializers.ChoiceField(["active", "left"])
    hire_date = serializers.DateField(allow_null=True)
    left_on = serializers.DateField(allow_null=True)
    schedule = NamedSerializer(allow_null=True)
    telegram_linked = serializers.BooleanField()
    is_user = serializers.BooleanField(help_text="Signs in to the web app too.")
    source = serializers.ChoiceField(["manual", "import", "terminal"])
    today = TodaySerializer(allow_null=True)

    class Meta:
        ref_name = "DavomatEmployee"


class EmployeeWriteSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    hire_date = serializers.DateField(required=False, allow_null=True)
    schedule_id = serializers.IntegerField(required=False, allow_null=True)
    face_numbers = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, max_length=20
    )

    class Meta:
        ref_name = "DavomatEmployeeWrite"


class LeaveSerializer(serializers.Serializer):
    left_on = serializers.DateField(required=False, allow_null=True, help_text="Today if empty.")

    class Meta:
        ref_name = "DavomatLeave"


class ReturnSerializer(serializers.Serializer):
    hire_date = serializers.DateField(required=False, allow_null=True, help_text="Today if empty.")

    class Meta:
        ref_name = "DavomatReturn"


class FaceNumberSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=32, help_text='As the terminal shows it: "00000002".')

    class Meta:
        ref_name = "DavomatFaceNumber"


class PhotoSerializer(serializers.Serializer):
    photo = serializers.ImageField()

    class Meta:
        ref_name = "DavomatPhoto"


class ImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="XLSX or CSV.")

    class Meta:
        ref_name = "DavomatImportUpload"


class ImportRowSerializer(serializers.Serializer):
    row = serializers.IntegerField(help_text="The row number in the file (the header is 1).")
    action = serializers.ChoiceField(["create", "update", "skip"])
    name = serializers.CharField()
    employee_id = serializers.IntegerField(allow_null=True)
    errors = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "DavomatImportRow"


class ImportResultSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    columns = serializers.ListField(child=serializers.CharField())
    mapping = serializers.DictField(
        child=serializers.CharField(), help_text="{column header: field}"
    )
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    skipped = serializers.IntegerField()
    rows = ImportRowSerializer(many=True, help_text="At most 500.")

    class Meta:
        ref_name = "DavomatImportResult"


class TelegramLinkSerializer(serializers.Serializer):
    url = serializers.CharField(help_text="https://t.me/<bot>?start=link_<code>")
    code = serializers.CharField()
    expires_at = serializers.DateTimeField()

    class Meta:
        ref_name = "DavomatTelegramLink"


# Telegram and settings -----------------------------------------------------------------------


class TelegramSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True, max_length=200, help_text="From BotFather.")
    configured = serializers.BooleanField(read_only=True)
    bot_username = serializers.CharField(read_only=True, allow_null=True)
    bot_name = serializers.CharField(read_only=True, allow_null=True)
    status = serializers.ChoiceField(DavomatSettings.BotStatus.choices, read_only=True)
    checked_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        ref_name = "DavomatTelegram"


class SentSerializer(serializers.Serializer):
    sent = serializers.BooleanField()

    class Meta:
        ref_name = "DavomatSent"


class SettingsSerializer(serializers.Serializer):
    product_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    auto_create_employees = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "DavomatSettings"
