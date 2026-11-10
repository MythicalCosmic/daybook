"""A policy's text: the dashboard editor's HTML cleaned by the knowledge base's allow-list
(`apps.knowledge.sanitize`), without pictures (a policy's pictures go in its file), and its
plain text, one line per block, for search and for comparing two versions."""

import re

from apps.knowledge.sanitize import clean, to_text

# Roughly sixty printed pages of rules: anything longer is a document for the file.
MAX_BODY_CHARS = 200_000
PICTURE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
EMPTY_PARAGRAPH = re.compile(r"<p>\s*</p>")


def clean_body(raw: str) -> str:
    """`raw` as it may be stored and shown: allowed markup only, no pictures, no empty ends."""
    html = PICTURE.sub("", clean(raw or ""))
    return EMPTY_PARAGRAPH.sub("", html).strip()


def text_of(body: str) -> str:
    return to_text(body or "")
