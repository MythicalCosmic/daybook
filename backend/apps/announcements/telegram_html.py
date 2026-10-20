"""Announcement text in Telegram's HTML subset, and nothing else.

Telegram accepts a handful of tags (https://core.telegram.org/bots/api#html-style). The
dashboard's composer (Tiptap) writes ordinary HTML: paragraphs, `<strong>`, `<em>`, a spoiler
span… `from_editor()` turns that into the Telegram subset, and `clean()` keeps a text that is
already Telegram HTML (the bot's `/announce`) to the same subset. Both escape every other
character, so whatever a browser sends, what we store and send is safe to show anywhere.

    from_editor("<p>Hi <strong>all</strong></p><p></p><p>Bye</p>") == "Hi <b>all</b>\\n\\nBye"
"""

from html import escape, unescape
from html.parser import HTMLParser

# Editor or Telegram tag -> the Telegram tag we write.
INLINE = {
    "b": "b",
    "strong": "b",
    "i": "i",
    "em": "i",
    "u": "u",
    "ins": "u",
    "s": "s",
    "strike": "s",
    "del": "s",
    "code": "code",
    "tg-spoiler": "tg-spoiler",
    "pre": "pre",
    "blockquote": "blockquote",
}
BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol"}
DROPPED = {"script", "style", "template", "iframe", "object"}
SAFE_SCHEMES = ("http://", "https://", "tg://", "mailto:")
EMPTY_PAIRS = ("b", "i", "u", "s", "code", "tg-spoiler", "pre", "blockquote", "a")


class _Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        # Telegram tags open now, outermost first: (name, opening tag text).
        self.stack: list[tuple[str, str]] = []
        # Source tags seen and not closed yet: (source name, Telegram name or None).
        self.sources: list[tuple[str, str | None]] = []
        self.dropping = 0

    def _write_close(self, name: str):
        self.out.append(f"</{name}>")

    def _newline(self):
        """A line break between blocks, closing and reopening tags around it."""
        if not self.out:
            return
        for name, _opening in reversed(self.stack):
            self._write_close(name)
        self.out.append("\n")
        for _name, opening in self.stack:
            self.out.append(opening)

    def handle_starttag(self, tag, attrs):
        if tag in DROPPED:
            self.dropping += 1
            return
        if self.dropping:
            return
        attrs = dict(attrs)
        if tag == "br":
            self.out.append("\n")
            return
        if tag in BLOCKS:
            just_bulleted = bool(self.out) and self.out[-1] == "• "
            if tag not in ("ul", "ol") and not just_bulleted:
                self._newline()
            if tag == "li":
                self.out.append("• ")
            self.sources.append((tag, None))
            return
        name, opening = None, None
        if tag == "span" and "tg-spoiler" in (attrs.get("class") or "").split():
            name, opening = "tg-spoiler", "<tg-spoiler>"
        elif tag == "a":
            href = (attrs.get("href") or "").strip()
            if href.lower().startswith(SAFE_SCHEMES):
                name, opening = "a", f'<a href="{escape(href, quote=True)}">'
        elif tag in INLINE:
            name = INLINE[tag]
            opening = f"<{name}>"
            if name == "code" and self.stack and self.stack[-1][0] == "pre":
                name = None  # <pre><code> is one block in Telegram
        if name is not None and any(open_name == name for open_name, _ in self.stack):
            name = None  # Telegram refuses the same tag inside itself
        if name is not None:
            if name in ("pre", "blockquote") and self.out and not self.out[-1].endswith("\n"):
                self._newline()
            self.stack.append((name, opening))
            self.out.append(opening)
        self.sources.append((tag, name))

    def handle_endtag(self, tag):
        if tag in DROPPED:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping or tag == "br":
            return
        for index in range(len(self.sources) - 1, -1, -1):
            source, name = self.sources[index]
            if source != tag:
                continue
            del self.sources[index]
            if name is not None:
                self._close(name)
            return

    def _close(self, name: str):
        """Close `name`, closing and reopening whatever opened inside it."""
        position = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == name), None
        )
        if position is None:
            return
        inner = self.stack[position + 1 :]
        for inner_name, _opening in reversed(inner):
            self._write_close(inner_name)
        self._write_close(name)
        del self.stack[position:]
        for inner_name, opening in inner:
            self.stack.append((inner_name, opening))
            self.out.append(opening)

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        for name, _opening in reversed(self.stack):
            self._write_close(name)
        self.stack.clear()
        text = "".join(self.out)
        changed = True
        while changed:
            before = text
            for tag in EMPTY_PAIRS:
                text = text.replace(f"<{tag}></{tag}>", "")
            changed = text != before
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()


def from_editor(html: str) -> str:
    """The composer's HTML as Telegram HTML (paragraphs become lines)."""
    converter = _Converter()
    converter.feed(html or "")
    converter.close()
    return converter.result()


def clean(text: str) -> str:
    """Telegram HTML kept to the allowed tags; anything else is escaped or dropped."""
    return from_editor((text or "").replace("\r\n", "\n"))


def plain(text: str) -> str:
    """The words without any formatting, for titles, search and previews."""
    stripped = _Stripper()
    stripped.feed(text or "")
    stripped.close()
    return unescape("".join(stripped.parts)).strip()


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
