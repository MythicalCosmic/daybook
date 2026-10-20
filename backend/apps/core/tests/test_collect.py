"""Beat entries and enum names that apps add from their own files (apps.core.collect)."""

import textwrap

import pytest
from celery.schedules import crontab
from django.conf import settings

from apps.core.collect import DuplicateKey, collect, sources
from apps.core.schema import enum_name_overrides


def write(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(text))


@pytest.fixture
def apps_dir(tmp_path):
    # Importing either package would fail: the files must be read by path, never imported.
    write(tmp_path, "sales/__init__.py", "raise RuntimeError('app imported at settings time')")
    write(tmp_path, "payroll/__init__.py", "raise RuntimeError('app imported at settings time')")
    write(
        tmp_path,
        "sales/beat.py",
        """
        from celery.schedules import crontab

        SCHEDULE = {
            "sales.operational-scan": {
                "task": "apps.sales.tasks.operational_scan",
                "schedule": crontab(minute="*/5"),
            },
        }
        """,
    )
    write(
        tmp_path,
        "payroll/beat.py",
        """
        from datetime import timedelta

        SCHEDULE = {"payroll.reminders": {"task": "x", "schedule": timedelta(hours=1)}}
        """,
    )
    write(
        tmp_path, "sales/schema_enums.py", 'ENUM_NAME_OVERRIDES = {"SalesShiftStatusEnum": "a.B"}'
    )
    write(tmp_path, "payroll/schema_enums.py", "ENUM_NAME_OVERRIDES = {}")
    write(tmp_path, "empty/__init__.py", "")  # an app without the file
    return tmp_path


def test_every_apps_entries_are_merged_with_the_base(apps_dir):
    schedule = collect("beat.py", "SCHEDULE", {"existing": {"task": "t"}}, apps_dir=apps_dir)

    assert list(schedule) == ["existing", "payroll.reminders", "sales.operational-scan"]
    assert schedule["sales.operational-scan"]["schedule"] == crontab(minute="*/5")


def test_a_key_used_twice_stops_the_settings(apps_dir):
    write(apps_dir, "payroll/beat.py", 'SCHEDULE = {"sales.operational-scan": {}}')

    with pytest.raises(DuplicateKey, match=r"'sales.operational-scan' from apps.sales"):
        collect("beat.py", "SCHEDULE", apps_dir=apps_dir)


def test_an_app_may_not_reuse_a_base_key(apps_dir):
    with pytest.raises(DuplicateKey, match="already defined by settings"):
        collect("beat.py", "SCHEDULE", {"payroll.reminders": {}}, apps_dir=apps_dir)


def test_enum_names_are_merged_and_duplicates_raise(apps_dir):
    merged = enum_name_overrides({"TaskStatusEnum": "x.Y"}, apps_dir=apps_dir)
    assert merged == {"TaskStatusEnum": "x.Y", "SalesShiftStatusEnum": "a.B"}

    write(apps_dir, "payroll/schema_enums.py", 'ENUM_NAME_OVERRIDES = {"SalesShiftStatusEnum": 1}')
    with pytest.raises(DuplicateKey):
        enum_name_overrides({}, apps_dir=apps_dir)


def test_the_attribute_must_be_a_dict(apps_dir):
    write(apps_dir, "payroll/beat.py", "SCHEDULE = []")

    with pytest.raises(TypeError, match="SCHEDULE must be a dict"):
        collect("beat.py", "SCHEDULE", apps_dir=apps_dir)


def test_the_settings_merge_the_real_apps():
    # The original entries survive the merge, and the hook is wired.
    assert "generate-daily-tasks" in settings.CELERY_BEAT_SCHEDULE
    assert "send-due-reminders" in settings.CELERY_BEAT_SCHEDULE
    overrides = settings.SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]
    assert overrides["TaskStatusEnum"] == "apps.tasks.models.Task.Status"
    assert settings.SPECTACULAR_SETTINGS["PREPROCESSING_HOOKS"] == [
        "apps.core.schema.split_by_audience"
    ]
    assert settings.CELERY_TASK_ROUTES == {"apps.ai.tasks.*": {"queue": "ai"}}


def pascal(label: str) -> str:
    return "".join(part.capitalize() for part in label.split("_"))


def test_app_enum_names_start_with_their_app_label():
    for label, overrides in sources("schema_enums.py", "ENUM_NAME_OVERRIDES"):
        for name in overrides:
            assert name.startswith(pascal(label)), f"apps.{label}: {name}"


def test_app_beat_entries_run_their_own_tasks():
    for label, schedule in sources("beat.py", "SCHEDULE"):
        for name, entry in schedule.items():
            assert entry["task"].startswith(f"apps.{label}.tasks."), f"apps.{label}: {name}"
