"""Nothing either bot sends carries an emoji (the owner's rule, 25.10.2026)."""

import ast
from pathlib import Path

import pytest
from django.conf import settings

from apps.notifications.emoji import has_emoji, plain_label, strip_emoji

ROOT = Path(settings.BASE_DIR).parent
# Every module the bots' texts come from: the backend apps (bot_messages, notifications, hooks,
# digests, services that name outcomes) and both bots.
SOURCES = [ROOT / "backend" / "apps", ROOT / "employee_bot", ROOT / "owner_bot"]
# Where an emoji alone is an icon the mini app and the dashboard draw (knowledge spaces and
# pages); the bots never print them.
ICON_FILES = {"backend/apps/knowledge/demo.py", "backend/apps/knowledge/defaults.py"}


@pytest.mark.parametrize(
    ("text", "plain"),
    [
        ("✅ Done", "Done"),
        ("📨 <b>New task</b> · %(name)s", "<b>New task</b> · %(name)s"),
        ("Menyu yangilandi 👇", "Menyu yangilandi"),
        ("Open: 5 · 🔴 late: 3", "Open: 5 · late: 3"),
        ("<b>✅ Done</b>", "<b>Done</b>"),
        ("1️⃣ Birinchi", "Birinchi"),
        ("👨‍👩‍👧 Oila", "Oila"),
        ("    📋 /tasks\n    ➕ /new", "    /tasks\n    /new"),
        ("«Kassa» — 12 500 so‘m · bugun, 18:30…", "«Kassa» — 12 500 so‘m · bugun, 18:30…"),
    ],
)
def test_strip_emoji(text, plain):
    assert strip_emoji(text) == plain
    assert not has_emoji(strip_emoji(text))


def test_plain_label_matches_old_and_new_keyboard_buttons():
    assert plain_label("📋  Vazifalarim ") == plain_label("Vazifalarim") == "Vazifalarim"
    assert plain_label("🏢 Demo Dorixona ▸") == "Demo Dorixona ▸"


@pytest.mark.parametrize(
    "text", ["✅", "☑️", "1️⃣", "🇺🇿", "✓ Tayyor", "Demo ▸", "Kassir → Olim", "★", "⚪"]
)
def test_has_emoji_counts_emoji_and_their_stand_ins(text):
    assert has_emoji(text)


@pytest.mark.parametrize("text", ["«Kassa» — 12 500 so‘m", "Holati: Bajarish kerak · 18:30…"])
def test_typography_is_not_emoji(text):
    assert not has_emoji(text)


def bot_sources():
    for source in SOURCES:
        for path in sorted(source.rglob("*.py")):
            parts = path.relative_to(ROOT).parts
            if "tests" in parts or "migrations" in parts or path.name.startswith("test_"):
                continue
            yield path


def literals(path: Path):
    """(line, text) for each string literal of a module, f-string parts included. Left out, as
    never sent: docstrings and other bare strings, `__str__` (the admin's labels), the values of
    `OLD_…` names (what keyboards from before 25.10.2026 send, to recognise them), and the
    knowledge icons."""
    tree = ast.parse(path.read_text(), filename=str(path))
    icons = path.relative_to(ROOT).as_posix() in ICON_FILES
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skipped.add(id(node.value))
        elif isinstance(node, ast.FunctionDef) and node.name in ("__str__", "__repr__"):
            skipped.update(id(inner) for inner in ast.walk(node))
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.startswith("OLD_") for target in node.targets
        ):
            skipped.update(id(inner) for inner in ast.walk(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            icon = icons and not strip_emoji(node.value).strip()
            if id(node) not in skipped and not icon:
                yield node.lineno, node.value


def test_the_bots_texts_have_no_emoji():
    found = [
        f"{path.relative_to(ROOT)}:{line}: {text!r}"
        for path in bot_sources()
        for line, text in literals(path)
        if has_emoji(text)
    ]
    assert found == []
