from unittest import mock

import pytest
from django.db import connection, models
from django.test.utils import isolate_apps

from apps.companies.models import Company
from apps.core.settings_rows import get_or_create_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def settings_model():
    """A settings model like FinanceSettings, with its table, for this test only."""
    with isolate_apps("apps.core"):

        class DemoSettings(models.Model):
            company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="+")
            limit = models.PositiveIntegerField(default=5)

            class Meta:
                app_label = "core"

            def __str__(self):
                return f"{self.company} settings"

        with connection.schema_editor() as editor:
            editor.create_model(DemoSettings)
        yield DemoSettings


def test_the_row_is_created_with_defaults_on_first_read(settings_model, company):
    row = get_or_create_for(settings_model, company)

    assert row.pk is not None
    assert row.company == company
    assert row.limit == 5


def test_later_reads_return_the_same_row(settings_model, company, other_company):
    first = get_or_create_for(settings_model, company)
    first.limit = 9
    first.save()

    again = get_or_create_for(settings_model, company)
    other = get_or_create_for(settings_model, other_company)

    assert again.pk == first.pk
    assert again.limit == 9
    assert other.pk != first.pk
    assert settings_model.objects.count() == 2


def test_a_concurrent_create_reads_the_winners_row(settings_model, company):
    winner = settings_model.objects.create(company=company, limit=7)

    # Both requests found nothing; this one loses the race on the unique constraint.
    with mock.patch("django.db.models.query.QuerySet.first", return_value=None):
        row = get_or_create_for(settings_model, company)

    assert row.pk == winner.pk
    assert row.limit == 7
