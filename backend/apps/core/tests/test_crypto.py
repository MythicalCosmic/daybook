import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, models
from django.db.migrations.writer import MigrationWriter

from apps.core import crypto
from apps.core.crypto import DecryptionError, DigestField, EncryptedTextField, digest, mask


class Secretive(models.Model):
    pinfl = EncryptedTextField(plain_max_length=14, blank=True)
    pinfl_digest = DigestField(of="pinfl")
    note = EncryptedTextField(null=True, blank=True)

    class Meta:
        app_label = "core"

    def __str__(self):
        return f"Secretive {self.pk}"


@pytest.fixture
def table(db):
    # apps.core has no migrations, so the test database may already have the table.
    if Secretive._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(Secretive)
    return Secretive


def raw(pk: int, column: str):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {Secretive._meta.db_table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


def test_values_are_stored_encrypted_and_read_back_plain(table):
    row = table.objects.create(pinfl="31234567890123", note="Allergic to nuts")

    assert raw(row.pk, "pinfl") != "31234567890123"
    assert "3123456" not in raw(row.pk, "pinfl")
    assert "nuts" not in raw(row.pk, "note")
    fresh = table.objects.get(pk=row.pk)
    assert fresh.pinfl == "31234567890123"
    assert fresh.note == "Allergic to nuts"


def test_the_digest_follows_the_value_on_every_save(table):
    row = table.objects.create(pinfl="31234567890123")
    assert row.pinfl_digest == digest("31234567890123")
    assert raw(row.pk, "pinfl_digest") == digest("31234567890123")

    row.pinfl = "40000000000000"
    row.save()

    assert table.objects.get(pinfl_digest=digest("4000 0000 000000")) == row


def test_empty_values_stay_empty_and_null_stays_null(table):
    row = table.objects.create(pinfl="", note=None)

    assert raw(row.pk, "pinfl") == ""
    assert raw(row.pk, "note") is None
    assert row.pinfl_digest == ""
    assert table.objects.filter(pinfl="").count() == 1
    assert table.objects.filter(note__isnull=True).count() == 1


def test_searching_ciphertext_is_refused_loudly(table):
    with pytest.raises(NotImplementedError):
        list(table.objects.filter(pinfl="31234567890123"))
    with pytest.raises(NotImplementedError):
        list(table.objects.filter(pinfl__icontains="312"))


def test_the_plain_length_is_validated_not_the_column(table):
    row = table(pinfl="1" * 15)
    with pytest.raises(ValidationError):
        row.full_clean(exclude=["note"])
    row.pinfl = "1" * 14
    row.full_clean(exclude=["note"])
    row.save()
    assert len(raw(row.pk, "pinfl")) > 14


def test_keys_rotate_newest_first(table, settings):
    old_key = settings.FIELD_ENCRYPTION_KEY
    row = table.objects.create(pinfl="31234567890123")

    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEY = f"{new_key},{old_key}"
    assert table.objects.get(pk=row.pk).pinfl == "31234567890123"  # old rows still read

    assert crypto.reencrypt(table.objects.all(), "pinfl", "note") == 1
    settings.FIELD_ENCRYPTION_KEY = new_key  # the old key retired
    assert table.objects.get(pk=row.pk).pinfl == "31234567890123"


def test_a_missing_key_fails_clearly(table, settings):
    row = table.objects.create(pinfl="31234567890123")
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(DecryptionError):
        table.objects.get(pk=row.pk)
    settings.FIELD_ENCRYPTION_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        table.objects.create(pinfl="1")
    settings.FIELD_ENCRYPTION_KEY = "not-a-fernet-key"
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("1")


def test_digests_ignore_spaces_and_case():
    assert digest("aa 1234567") == digest("AA1234567") == digest(" Aa\t12 34 567 ")
    assert digest("AA1234567") != digest("AA1234568")
    assert digest("") == digest("   ") == digest(None) == ""
    assert len(digest("x")) == 64


def test_digests_depend_on_the_key(settings):
    first = digest("AA1234567")
    settings.FIELD_HASH_KEY = "another key"
    assert digest("AA1234567") != first
    settings.FIELD_HASH_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        digest("AA1234567")


@pytest.mark.parametrize(
    ("value", "keep", "masked"),
    [
        ("8600 1234 5678 9012", 4, "••••••••••••9012"),
        ("AA1234567", 4, "•••••4567"),
        ("1234", 4, "••••"),
        ("12345", 0, "•••••"),
        ("", 4, ""),
        (None, 4, ""),
    ],
)
def test_masking(value, keep, masked):
    assert mask(value, keep=keep) == masked


def test_fields_deconstruct_for_migrations():
    field = EncryptedTextField(plain_max_length=14, blank=True)
    _name, path, _args, kwargs = field.deconstruct()
    assert path == "apps.core.crypto.EncryptedTextField"
    assert kwargs == {"plain_max_length": 14, "blank": True}
    assert "validators" not in kwargs

    _name, path, _args, kwargs = DigestField(of="pinfl").deconstruct()
    assert path == "apps.core.crypto.DigestField"
    assert kwargs["of"] == "pinfl"
    assert MigrationWriter.serialize(DigestField(of="pinfl"))[0]
