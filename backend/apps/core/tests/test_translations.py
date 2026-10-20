"""Everything the bots and the API say exists in Uzbek and Russian. `make messages` updates it."""

import re
import shutil

import polib
import pytest
from django.conf import settings
from django.core.management import call_command

LANGUAGES = ("uz", "ru")
# Placeholders and markup a translation must keep exactly.
KEPT = re.compile(r"%\(\w+\)[sd]|\{\w+\}|</?\w+>")


def catalogue(language: str, kind: str = "po"):
    path = settings.LOCALE_PATHS[0] / language / "LC_MESSAGES" / f"django.{kind}"
    return polib.pofile(str(path)) if kind == "po" else polib.mofile(str(path))


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_message_is_translated(language):
    po = catalogue(language)

    assert [entry.msgid for entry in po.untranslated_entries()] == []
    assert [entry.msgid for entry in po.fuzzy_entries()] == []
    for entry in po.translated_entries():
        assert sorted(KEPT.findall(entry.msgstr)) == sorted(KEPT.findall(entry.msgid)), entry.msgid


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_compiled_catalogues_match_their_sources(language):
    sources = {entry.msgid: entry.msgstr for entry in catalogue(language).translated_entries()}
    compiled = {entry.msgid: entry.msgstr for entry in catalogue(language, "mo") if entry.msgid}

    assert compiled == sources


@pytest.mark.skipif(shutil.which("xgettext") is None, reason="needs GNU gettext")
def test_no_message_is_missing_from_the_catalogues(settings, tmp_path, monkeypatch):
    known = {entry.msgid for entry in catalogue("uz")}
    # makemessages writes into every locale directory it finds, so it reads a copy of the code.
    root = settings.BASE_DIR.parent
    skip = shutil.ignore_patterns("locale", "tests", "migrations", "__pycache__")
    for source in ("backend/apps", "backend/config", "employee_bot"):
        shutil.copytree(root / source, tmp_path / "code" / source, ignore=skip)
    monkeypatch.chdir(tmp_path / "code")
    settings.LOCALE_PATHS = [tmp_path / "locale"]

    call_command("makemessages", locale=["uz"], verbosity=0)

    extracted = polib.pofile(str(tmp_path / "locale/uz/LC_MESSAGES/django.po"))
    found = {entry.msgid for entry in extracted}
    assert found - known == set(), "new texts: run `make messages` and translate them"
    assert known - found == set(), "unused texts: run `make messages`"
