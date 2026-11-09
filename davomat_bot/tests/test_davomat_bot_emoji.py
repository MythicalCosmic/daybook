"""Nothing the Davomat bot sends carries an emoji or a stand-in (the owner's rule, 25.10.2026):
the same scan as `apps.notifications.tests.test_emoji`, over this package."""

from pathlib import Path

from apps.notifications.emoji import has_emoji
from apps.notifications.tests.test_emoji import literals

PACKAGE = Path(__file__).resolve().parents[1]


def sources():
    for path in sorted(PACKAGE.rglob("*.py")):
        if "tests" in path.relative_to(PACKAGE).parts:
            continue
        yield path


def test_the_bots_texts_have_no_emoji():
    found = [
        f"{path.name}:{line}: {text!r}"
        for path in sources()
        for line, text in literals(path)
        if has_emoji(text)
    ]
    assert found == []
    assert len(list(sources())) > 10  # the scan sees the package
