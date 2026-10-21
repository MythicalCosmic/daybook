"""Cleaning page bodies, and turning them into text (search, excerpts) and Telegram HTML.

The dashboard editor sends HTML. Before it is stored it goes through `clean()`, an allow-list:
only the tags and attributes the editor makes survive (headings, paragraphs, lists, checklists,
callouts, tables, quotes, code, links, our own pictures). Everything else is dropped: unknown
tags lose their markup but keep their text; `<script>`, `<style>` and the like lose their
content too; every `on…` handler, `style`, `class` and unknown attribute goes; links keep only
http(s), mailto and tel addresses and open in a new tab without a referrer.

Pictures are stored as `<img data-image-id="12">` without a `src`: a page is read by many
people, and each reader gets their own short signed link (`with_image_urls`).

It uses only the standard library's tokenizer (no third-party sanitizer is installed), and it
re-serializes every tag itself, so the output is balanced and every value is escaped.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from html.parser import HTMLParser

MAX_BODY_CHARS = 400_000

# Tags and the attributes each may keep. Values are checked again in `_attr`.
ALLOWED: dict[str, frozenset[str]] = {
    "p": frozenset(),
    "h1": frozenset(),
    "h2": frozenset(),
    "h3": frozenset(),
    "h4": frozenset(),
    "strong": frozenset(),
    "b": frozenset(),
    "em": frozenset(),
    "i": frozenset(),
    "u": frozenset(),
    "s": frozenset(),
    "strike": frozenset(),
    "code": frozenset(),
    "pre": frozenset(),
    "blockquote": frozenset(),
    "br": frozenset(),
    "hr": frozenset(),
    "ul": frozenset({"data-type"}),
    "ol": frozenset({"start"}),
    "li": frozenset({"data-type", "data-checked"}),
    "label": frozenset(),
    "input": frozenset({"type", "checked", "disabled"}),
    "span": frozenset(),
    "div": frozenset({"data-callout"}),
    "a": frozenset({"href"}),
    "img": frozenset({"data-image-id", "alt"}),
    "table": frozenset(),
    "thead": frozenset(),
    "tbody": frozenset(),
    "tr": frozenset(),
    "th": frozenset({"colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
    "colgroup": frozenset(),
    "col": frozenset(),
}
VOID = frozenset({"br", "hr", "img", "input", "col"})
# Dropped with everything inside them.
DROP_WITH_CONTENT = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "template",
        "noscript",
        "svg",
        "math",
        "textarea",
        "select",
        "title",
        "head",
        "frame",
        "frameset",
        "applet",
        "audio",
        "video",
        "canvas",
        "form",
        "button",
    }
)
CALLOUT_TONES = frozenset({"info", "success", "warning", "danger", "note"})
SAFE_URL = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)
TRAILING_EMPTY = re.compile(r"(?:\s*<p>(?:<br>)?</p>)+\s*$")
BLOCKS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "blockquote",
        "pre",
        "div",
        "tr",
        "table",
        "ul",
        "ol",
        "hr",
        "br",
    }
)


def _attr(tag: str, name: str, value: str | None) -> str | None:
    """The cleaned value of an allowed attribute, or None to drop it."""
    value = (value or "").strip()
    match (tag, name):
        case ("a", "href"):
            return value if SAFE_URL.match(value) and len(value) <= 2000 else None
        case ("ul", "data-type"):
            return value if value == "taskList" else None
        case ("li", "data-type"):
            return value if value == "taskItem" else None
        case ("li", "data-checked"):
            return "true" if value == "true" else "false"
        case ("input", "type"):
            return "checkbox" if value == "checkbox" else None
        case ("input", "checked") | ("input", "disabled"):
            return name
        case ("div", "data-callout"):
            return value if value in CALLOUT_TONES else None
        case ("img", "data-image-id"):
            return value if value.isdigit() and len(value) <= 12 else None
        case ("img", "alt"):
            return value[:200]
        case (
            ("ol", "start")
            | ("th", "colspan")
            | ("th", "rowspan")
            | ("td", "colspan")
            | (
                "td",
                "rowspan",
            )
        ):
            return value if value.isdigit() and 0 < int(value) <= 1000 else None
    return None


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip = 0  # depth inside a DROP_WITH_CONTENT element

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_WITH_CONTENT and tag not in VOID:
                self.skip += 1
            return
        if tag in DROP_WITH_CONTENT:
            self.skip = 1
            return
        if tag not in ALLOWED:
            return
        kept = []
        for name, value in attrs:
            if name not in ALLOWED[tag]:
                continue
            clean = _attr(tag, name, value)
            if clean is not None:
                kept.append((name, clean))
        if tag == "img":
            if not any(name == "data-image-id" for name, _value in kept):
                return  # only our own pictures
            # The id first: `with_image_urls` finds pictures by it.
            kept.sort(key=lambda pair: pair[0] != "data-image-id")
        if tag == "input" and ("type", "checkbox") not in kept:
            return
        if tag == "a" and not kept:
            return  # a link to nowhere (javascript:, data:…) keeps only its text
        rendered = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            if name not in ("checked", "disabled")
            else f" {name}"
            for name, value in kept
        )
        if tag == "a":
            rendered += ' target="_blank" rel="noopener noreferrer nofollow"'
        self.out.append(f"<{tag}{rendered}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in DROP_WITH_CONTENT:
                self.skip -= 1
            return
        if tag not in ALLOWED or tag in VOID or tag not in self.stack:
            return
        # Close whatever was left open inside it, so the output stays balanced.
        while self.stack:
            open_tag = self.stack.pop()
            self.out.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def clean(raw: str) -> str:
    """`raw` HTML with only the allowed markup left; safe to store and to show."""
    if not raw:
        return ""
    cleaner = _Cleaner()
    cleaner.feed(raw[: MAX_BODY_CHARS * 2])
    cleaner.close()
    # An editor's empty document is "<p></p>", and it keeps an empty paragraph after a last
    # callout, table or picture so there is somewhere to type: neither is content.
    return TRAILING_EMPTY.sub("", cleaner.result()).strip()


class _Render(HTMLParser):
    """A (clean) body as lines: plain text (`telegram=False`) or the subset of HTML Telegram
    renders (<b>, <i>, <u>, <s>, <code>, <pre>, <a>, <blockquote>). Lists keep their bullets,
    numbers and checkboxes; table rows become one line with " · " between cells."""

    INLINE = {"strong": "b", "b": "b", "em": "i", "i": "i", "u": "u", "s": "s", "strike": "s"}
    CALLOUT_MARKS = {"warning": "⚠️", "danger": "⛔️", "success": "✅", "note": "📝"}

    def __init__(self, *, telegram: bool):
        super().__init__(convert_charrefs=True)
        self.telegram = telegram
        self.out: list[str] = []
        self.line = ""
        self.has_text = False
        self.lists: list[list] = []  # [kind, next number]
        self.quotes: list[str] = []  # "quote" | "callout"
        self.links = 0
        self.cells = 0
        self.pre = False

    # Lines ---------------------------------------------------------------------------

    def commit(self):
        self.out.append(self.line.rstrip())
        self.line = ""
        self.has_text = False

    def start_block(self, *, prefix: str = "", gap: bool = False):
        if self.has_text:
            self.commit()
        if gap and self.telegram and self.out and self.out[-1] != "" and not self.line:
            self.out.append("")
        if prefix:
            self.line += prefix

    def end_block(self):
        if self.has_text:
            self.commit()

    def tag(self, text: str):
        if self.telegram:
            self.line += text

    def close_on_last_line(self, text: str):
        """Closing markup for a block whose last line is already committed."""
        if not self.telegram:
            return
        if self.has_text or not self.out:
            self.line += text
        else:
            self.out[-1] += text

    # Parser --------------------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in self.INLINE:
            self.tag(f"<{self.INLINE[tag]}>")
        elif tag == "code" and not self.pre:
            self.tag("<code>")
        elif tag == "pre":
            self.start_block(gap=True)
            self.pre = True
            self.tag("<pre>")
        elif tag == "a":
            if attributes.get("href"):
                self.tag(f'<a href="{html.escape(attributes["href"], quote=True)}">')
                self.links += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.start_block(gap=True)
            self.tag("<b>")
        elif tag == "blockquote":
            self.start_block(gap=True)
            self.tag("<blockquote>")
            self.quotes.append("quote")
        elif tag == "div" and attributes.get("data-callout"):
            self.start_block(gap=True)
            self.tag("<blockquote>")
            mark = self.CALLOUT_MARKS.get(attributes["data-callout"], "💡")
            self.line += f"{mark} "
            self.quotes.append("callout")
        elif tag in ("ul", "ol"):
            self.start_block(gap=not self.lists)
            kind = "task" if attributes.get("data-type") == "taskList" else tag
            self.lists.append([kind, int(attributes.get("start") or 1)])
        elif tag == "li":
            kind, number = self.lists[-1] if self.lists else ("ul", 1)
            indent = "   " * max(0, len(self.lists) - 1)
            if kind == "task":
                checked = attributes.get("data-checked") == "true"
                mark = ("☑️ " if checked else "◻️ ") if self.telegram else ("☑ " if checked else "☐ ")
            elif kind == "ol":
                mark = f"{number}. "
                self.lists[-1][1] = number + 1
            else:
                mark = "• "
            self.start_block(prefix=indent + mark)
        elif tag in ("tr",):
            self.start_block()
        elif tag in ("td", "th"):
            if self.has_text:
                self.line += " · "
            self.cells += 1
        elif tag in ("p", "div") and not self.cells:
            self.start_block(gap=not self.lists and not self.quotes)
        elif tag == "br":
            if self.has_text:
                self.commit()
            else:
                self.out.append("")
        elif tag == "hr":
            self.start_block(gap=True)
            self.line += "———"
            self.has_text = True
            self.end_block()
        elif tag == "img":
            alt = attributes.get("alt") or ""
            self.line += (
                f"🖼 {html.escape(alt, quote=False)}".rstrip()
                if self.telegram
                else f"[{alt or '🖼'}]"
            )
            self.has_text = True

    def handle_endtag(self, tag):
        if tag in self.INLINE:
            self.tag(f"</{self.INLINE[tag]}>")
        elif tag == "code" and not self.pre:
            self.tag("</code>")
        elif tag == "pre":
            self.close_on_last_line("</pre>")
            self.pre = False
            self.end_block()
        elif tag == "a":
            if self.links:
                self.tag("</a>")
                self.links -= 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.tag("</b>")
            self.end_block()
        elif tag == "blockquote" or (tag == "div" and self.quotes and self.quotes[-1] == "callout"):
            if self.quotes:
                self.quotes.pop()
            self.close_on_last_line("</blockquote>")
            self.end_block()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.end_block()
        elif tag in ("td", "th"):
            self.cells = max(0, self.cells - 1)
        elif tag in ("tr", "li") or (tag in ("p", "div") and not self.cells):
            self.end_block()

    def handle_data(self, data):
        if not self.pre:
            data = re.sub(r"\s+", " ", data)
            if not self.has_text:
                data = data.lstrip()
        if not data:
            return
        self.line += html.escape(data, quote=False) if self.telegram else data
        self.has_text = True

    def result(self) -> str:
        self.end_block()
        text = "\n".join(self.out)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_text(body: str) -> str:
    """The plain text of a (clean) body: one line per block, list marks kept."""
    if not body:
        return ""
    renderer = _Render(telegram=False)
    renderer.feed(body)
    renderer.close()
    return renderer.result()


LIST_MARK = re.compile(r"^(?:[☐☑•]|\d{1,3}\.)\s+")
SENTENCE_END = (".", "!", "?", ":", "…", ";")


def excerpt(text: str, limit: int = 220) -> str:
    """The first `limit` characters of `text` on one line, cut at a word. Lines lose their list
    marks (bullets, checkboxes, numbers); a line that doesn't end a sentence (a list item, a
    table row) is joined to the next with " · " rather than run into it."""
    flat = ""
    for line in text.splitlines():
        line = LIST_MARK.sub("", " ".join(line.split()))
        if not line:
            continue
        if flat:
            flat += " " if flat.endswith(SENTENCE_END) else " · "
        flat += line
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def to_telegram(body: str, *, limit: int = 3500) -> tuple[str, bool]:
    """A (clean) body as Telegram HTML, and whether it was cut to fit one message."""
    renderer = _Render(telegram=True)
    renderer.feed(body or "")
    renderer.close()
    text = renderer.result()
    if len(text) <= limit:
        return text, False
    # Cut on a line, then drop the markup a cut may have broken: plain text is always valid.
    cut = text[:limit].rsplit("\n", 1)[0]
    plain = html.escape(re.sub(r"<[^>]+>", "", html.unescape(cut)), quote=False)
    return f"{plain}\n…", True


IMAGE_TAG = re.compile(r'<img data-image-id="(\d+)"')


def image_ids(body: str) -> set[int]:
    """The ids of the pictures a (clean) body shows."""
    return {int(found) for found in IMAGE_TAG.findall(body or "")}


def with_image_urls(body: str, url_for: Callable[[int], str | None]) -> str:
    """The body with a `src` on each picture (`url_for(image_id)`; None leaves it out)."""

    def replace(match: re.Match) -> str:
        url = url_for(int(match.group(1)))
        if not url:
            return match.group(0)
        return f'<img src="{html.escape(url, quote=True)}" data-image-id="{match.group(1)}"'

    return IMAGE_TAG.sub(replace, body or "")
