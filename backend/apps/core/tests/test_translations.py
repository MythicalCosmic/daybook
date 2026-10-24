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
PLACEHOLDER = r"(?:%\(\w+\)[sd]|\{\w+\})"
# Wording a translation must not have; the comments say what to write instead.
WORDING = {
    "uz": {
        # A case ending changes with the word before it (Otabekka, Ishoqqa) and no rule says how
        # one joins digits, so none goes on a placeholder or a number, glued or after a space:
        # "Kimdan: %(name)s", "%(title)s vazifasini", "Keyingi eslatma: %(time)s".
        "ending-after-placeholder": PLACEHOLDER
        + r"(?:</\w+>|»)?\s?(?:da|dan|dagi|ga|ka|qa|gacha|kacha|qacha|ni|ning|niki|dek)\b",
        "ending-after-number": r"\d[ -]?(?:da|dan|dagi|ga|gacha|ni|ning)\b",
        # ’ is the tutuq inside a word, never a suffix separator: Telegramda, Daybookni.
        "apostrophe-before-ending": r"\b[A-Z][A-Za-z]{2,}’(?:da|dan|dagi|ga|gacha|ni|ning|lar)\b",
        "curly-quotes": r"[“”„]",
    },
    "ru": {
        # Names don't decline: "Автор: %(name)s", "в компанию «%(company)s»".
        "preposition-before-name": r"\b(?:в|во|для|за|из|к|ко|на|о|об|от|по|при|с|со|у)\s+"
        r"(?:<b>|«)?(?:%\((?:name|names|person|cashier|receiver|manager|who|party|company|branch)"
        r"\)s|\{name\})",
        # Gender-neutral wording, not a bracketed ending: "%(person)s: вам передано …".
        "gender-brackets": r"\w\((?:а|-а|ла)\)",
        "curly-quotes": r"[“”„]",
    },
}
# Both languages quote with «…», and o‘, g‘ and the tutuq are ‘ and ’: outside markup a straight
# quote is a slip.
STRAIGHT_QUOTE = re.compile(r"[\"']")
TAG = re.compile(r"<[^>]*>")


def catalogue(language: str, kind: str = "po"):
    path = settings.LOCALE_PATHS[0] / language / "LC_MESSAGES" / f"django.{kind}"
    return polib.pofile(str(path)) if kind == "po" else polib.mofile(str(path))


def translations(language: str):
    """(msgid, text) for every translation, each plural form on its own."""
    for entry in catalogue(language).translated_entries():
        forms = entry.msgstr_plural.values() if entry.msgid_plural else [entry.msgstr]
        for form in dict.fromkeys(forms):
            yield entry.msgid, form


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_message_is_translated(language):
    po = catalogue(language)

    assert [entry.msgid for entry in po.untranslated_entries()] == []
    assert [entry.msgid for entry in po.fuzzy_entries()] == []
    for entry in po.translated_entries():
        # Uzbek has one plural form, Russian four; each keeps the plural msgid's placeholders.
        forms = entry.msgstr_plural.values() if entry.msgid_plural else [entry.msgstr]
        expected = sorted(KEPT.findall(entry.msgid_plural or entry.msgid))
        assert all(sorted(KEPT.findall(form)) == expected for form in forms), entry.msgid


@pytest.mark.parametrize(
    ("language", "rule"),
    [(language, rule) for language, rules in WORDING.items() for rule in rules],
)
def test_translations_follow_the_wording_rules(language, rule):
    pattern = re.compile(WORDING[language][rule])

    assert [msgid for msgid, text in translations(language) if pattern.search(text)] == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_translations_quote_with_guillemets(language):
    texts = translations(language)

    assert [msgid for msgid, text in texts if STRAIGHT_QUOTE.search(TAG.sub("", text))] == []


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
    for source in ("backend/apps", "backend/config", "employee_bot", "owner_bot"):
        shutil.copytree(root / source, tmp_path / "code" / source, ignore=skip)
    monkeypatch.chdir(tmp_path / "code")
    settings.LOCALE_PATHS = [tmp_path / "locale"]

    call_command("makemessages", locale=["uz"], verbosity=0)

    extracted = polib.pofile(str(tmp_path / "locale/uz/LC_MESSAGES/django.po"))
    found = {entry.msgid for entry in extracted}
    assert found - known == set(), "new texts: run `make messages` and translate them"
    assert known - found == set(), "unused texts: run `make messages`"
