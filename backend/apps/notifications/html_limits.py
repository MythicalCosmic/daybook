"""Telegram's HTML subset and its length limits (https://core.telegram.org/bots/api#html-style).

Both bots send HTML: every `<` opens or closes a supported tag, and every user's text (a name,
a task title, a comment) goes through `aiogram.html.quote` first. Telegram measures a text
after parsing it: tags don't count, an entity (`&amp;`) is one character, and characters are
UTF-16 code units. A message holds 4096 of them, a caption 1024.

    fit(text, CAPTION_LIMIT)   # cut at a line end, open tags closed, "…" at the end
    problems(text)             # what Telegram would refuse, or what looks unescaped (tests)
"""

import re

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
CALLBACK_DATA_LIMIT = 64  # bytes
TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "code",
        "del",
        "em",
        "i",
        "ins",
        "pre",
        "s",
        "span",
        "strike",
        "strong",
        "tg-emoji",
        "tg-spoiler",
        "u",
    }
)
MARKUP = re.compile(
    r"<(?P<close>/?)(?P<tag>[a-zA-Z][\w-]*)(?P<attrs>[^<>]*)>"
    r"|(?P<entity>&(?:#\d+|#x[\da-fA-F]+|[a-zA-Z]+);)"
    r"|(?P<bare>[<&])"
)
ELLIPSIS = "…"
# A cut at a line end is kept unless it would throw away more than this share of the room.
LINE_END_SLACK = 0.25


def _units(text: str) -> int:
    """Length as Telegram counts it: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def _parts(text: str):
    """("text", piece) runs and ("tag" | "entity" | "bare", match) pieces, in order."""
    position = 0
    for match in MARKUP.finditer(text):
        if match.start() > position:
            yield "text", text[position : match.start()], position
        kind = "tag" if match.group("tag") else "entity" if match.group("entity") else "bare"
        yield kind, match, match.start()
        position = match.end()
    if position < len(text):
        yield "text", text[position:], position


def visible_length(text: str) -> int:
    """How long Telegram finds `text` once its tags and entities are parsed."""
    length = 0
    for kind, part, _start in _parts(text):
        if kind == "text":
            length += _units(part)
        elif kind != "tag":
            length += 1
    return length


def fit(text: str, limit: int = TEXT_LIMIT) -> str:
    """`text` if Telegram takes it, else as much as fits: cut at the last line end that keeps
    most of it (or between two characters), the tags still open closed, then "…"."""
    if visible_length(text) <= limit:
        return text
    budget = limit - _units(ELLIPSIS)
    used = 0
    stack: list[str] = []
    line_end: tuple[int, list[str]] | None = None
    cut: tuple[int, list[str]] | None = None
    for kind, part, start in _parts(text):
        if kind == "tag":
            name = part.group("tag").lower()
            if part.group("close"):
                if name in stack:
                    del stack[len(stack) - 1 - stack[::-1].index(name)]
            else:
                stack.append(name)
            continue
        if kind != "text":
            if used + 1 > budget:
                cut = (start, list(stack))
                break
            used += 1
            continue
        for offset, char in enumerate(part):
            size = _units(char)
            if used + size > budget:
                cut = (start + offset, list(stack))
                break
            used += size
            if char == "\n":
                line_end = (start + offset, list(stack))
        if cut is not None:
            break
    if cut is None:  # only tags and entities past the budget
        cut = (len(text), stack)
    if line_end is not None and visible_length(text[: line_end[0]]) >= budget * (
        1 - LINE_END_SLACK
    ):
        cut = line_end
    end, still_open = cut
    closing = "".join(f"</{name}>" for name in reversed(still_open))
    return f"{text[:end].rstrip()}{closing}{ELLIPSIS}"


def problems(text: str, limit: int | None = None) -> list[str]:
    """Why Telegram would refuse `text` in HTML mode, plus a bare `&` (Telegram shows it, but it
    means someone's text skipped `html.quote`). Empty when it's fine."""
    found = []
    stack: list[str] = []
    for kind, part, start in _parts(text):
        if kind == "bare":
            found.append(f"unescaped {part.group(0)!r} at {start}: {text[start : start + 40]!r}")
        elif kind == "tag":
            name = part.group("tag").lower()
            if name not in TAGS:
                found.append(f"unsupported tag <{name}> at {start}: {text[start : start + 40]!r}")
            elif part.group("close"):
                if not stack or stack[-1] != name:
                    found.append(f"</{name}> at {start} closes nothing open")
                else:
                    stack.pop()
            else:
                if name == "a" and "href=" not in part.group("attrs"):
                    found.append(f"<a> without href at {start}")
                stack.append(name)
    if stack:
        found.append(f"left open: {', '.join(stack)}")
    if limit is not None and (length := visible_length(text)) > limit:
        found.append(f"{length} characters, more than {limit}")
    return found
