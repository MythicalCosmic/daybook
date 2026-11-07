"""Ask AI's answers in Telegram: the Markdown the dashboard renders, turned into the HTML a bot
message may carry (Telegram's small subset: b, i, code).

Everything is escaped first, so whatever the answer holds can't open a tag of its own; then,
line by line: headings and **bold** become bold, `code` code, *italics* italics, list markers
a bullet, record links ([Dilnoza](member:17), [Kirim](task:345)) their label, and table rows
cells joined with " · " (a phone has no room for a grid; the divider rows go).
"""

import re
from html import escape

HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
RECORD_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((?:member|task):\d{1,12}\)")
BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
ITALIC = re.compile(r"(?<![\*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\*\w])")
CODE = re.compile(r"`([^`\n]+)`")


def _inline(text: str) -> str:
    text = RECORD_LINK.sub(r"\1", text)
    text = CODE.sub(r"<code>\1</code>", text)
    text = BOLD.sub(r"<b>\1</b>", text)
    return ITALIC.sub(r"<i>\1</i>", text)


def to_telegram(markdown: str) -> str:
    """`markdown` as Telegram HTML; blank runs collapse to one empty line."""
    lines: list[str] = []
    for raw in escape(markdown or "", quote=False).splitlines():
        if TABLE_DIVIDER.match(raw):
            continue
        if row := TABLE_ROW.match(raw):
            cells = [cell.strip() for cell in row.group(1).split("|")]
            lines.append(_inline(" · ".join(cell for cell in cells if cell)))
            continue
        if heading := HEADING.match(raw):
            inner = _inline(heading.group(1)).replace("<b>", "").replace("</b>", "")
            lines.append(f"<b>{inner}</b>")
            continue
        if bullet := BULLET.match(raw):
            raw = bullet.group(1) + "• " + raw[bullet.end() :]
        lines.append(_inline(raw.rstrip()))
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)
