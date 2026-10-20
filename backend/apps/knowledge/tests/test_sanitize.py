"""Page bodies: the allow-list, plain text for search, and the Telegram rendering."""

import pytest

from apps.knowledge import sanitize

TASKS = (
    '<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><label>'
    '<input type="checkbox" checked="checked"><span></span></label><div><p>Count the float</p>'
    '</div></li><li data-type="taskItem" data-checked="false"><label><input type="checkbox">'
    "<span></span></label><div><p>Open the shift</p></div></li></ul>"
)


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script>",
        "<style>body{display:none}</style>",
        '<iframe src="https://evil.example"></iframe>',
        '<svg onload="alert(1)"><script>alert(1)</script></svg>',
        '<img src="x" onerror="alert(1)">',
        '<a href="javascript:alert(1)">click</a>',
        '<a href="data:text/html;base64,PHNjcmlwdD4=">click</a>',
        '<p onclick="steal()" style="background:url(javascript:x)">hi</p>',
        '<form action="https://evil"><input name="password"></form>',
        "<object data='x.swf'></object><embed src='x'>",
        '<math><mi xlink:href="javascript:alert(1)">x</mi></math>',
        '<div data-callout="info" onmouseover="x()">ok</div>',
    ],
)
def test_nothing_executable_survives(raw):
    clean = sanitize.clean(raw)

    lowered = clean.lower()
    for marker in ("<script", "javascript:", "onerror", "onload", "onclick", "onmouseover"):
        assert marker not in lowered
    for tag in ("<iframe", "<svg", "<style", "<object", "<embed", "<form", "<math", "style="):
        assert tag not in lowered


def test_the_editor_markup_survives():
    body = (
        "<h2>Opening</h2><p>Hi <strong>team</strong>, <em>read</em> <u>this</u> <s>not</s>"
        ' <code>F1</code> <a href="https://t.me/shop">chat</a></p>'
        '<ol start="2"><li><p>Two</p></li></ol><blockquote><p>Quote</p></blockquote>'
        '<div data-callout="warning"><p>Careful</p></div><hr>'
        '<table><tbody><tr><th colspan="2"><p>A</p></th></tr><tr><td><p>1</p></td>'
        "<td><p>2</p></td></tr></tbody></table>" + TASKS
    )

    clean = sanitize.clean(body)

    for kept in (
        "<h2>Opening</h2>",
        "<strong>team</strong>",
        '<ol start="2">',
        '<div data-callout="warning">',
        '<th colspan="2">',
        '<ul data-type="taskList">',
        '<li data-type="taskItem" data-checked="true">',
        '<input type="checkbox" checked>',
        "<hr>",
    ):
        assert kept in clean
    assert (
        '<a href="https://t.me/shop" target="_blank" rel="noopener noreferrer nofollow">' in clean
    )


def test_unknown_tags_keep_their_text_and_unclosed_tags_are_closed():
    assert sanitize.clean("<marquee>Sale!</marquee>") == "Sale!"
    assert sanitize.clean("<p>Open <b>now") == "<p>Open <b>now</b></p>"
    assert sanitize.clean("<p>a &lt;b&gt; &amp; c</p>") == "<p>a &lt;b&gt; &amp; c</p>"


def test_only_our_own_pictures_are_kept_and_their_src_is_dropped():
    clean = sanitize.clean(
        '<img alt="Till" src="https://evil/x.png" data-image-id="12"><img src="https://evil/y.png">'
    )

    assert clean == '<img data-image-id="12" alt="Till">'
    assert sanitize.image_ids(clean) == {12}
    shown = sanitize.with_image_urls(clean, lambda pk: f"/api/v1/files/t{pk}/")
    assert shown == '<img src="/api/v1/files/t12/" data-image-id="12" alt="Till">'


def test_an_empty_editor_document_is_empty():
    assert sanitize.clean("<p></p>") == ""
    assert sanitize.clean("") == ""


def test_plain_text_keeps_lists_checkboxes_and_tables():
    body = sanitize.clean(
        "<h2>Close</h2><p>Steps:</p><ol><li><p>Z report</p></li><li><p>Count</p></li></ol>"
        + TASKS
        + "<table><tbody><tr><td><p>Cash</p></td><td><p>Card</p></td></tr></tbody></table>"
    )

    assert sanitize.to_text(body) == (
        "Close\nSteps:\n1. Z report\n2. Count\n☑ Count the float\n☐ Open the shift\nCash · Card"
    )


def test_telegram_rendering_uses_only_what_telegram_understands():
    body = sanitize.clean(
        '<h2>Till</h2><p>Use <strong>F1</strong> <a href="https://t.me/x">here</a></p>'
        '<div data-callout="warning"><p>Never leave it open</p></div>' + TASKS
    )

    text, cut = sanitize.to_telegram(body)

    assert not cut
    assert text == (
        '<b>Till</b>\n\nUse <b>F1</b> <a href="https://t.me/x">here</a>\n\n'
        "<blockquote>⚠️ Never leave it open</blockquote>\n\n"
        "☑️ Count the float\n◻️ Open the shift"
    )
    for tag in ("<p>", "<h2>", "<div", "<ul", "<li"):
        assert tag not in text


def test_a_long_page_is_cut_for_telegram_as_safe_plain_text():
    body = "".join(f"<p><b>Step {n}</b>: count &amp; check</p>" for n in range(500))

    text, cut = sanitize.to_telegram(sanitize.clean(body), limit=300)

    assert cut
    assert len(text) < 320
    assert "<b>" not in text and "&amp;" in text
    assert text.endswith("…")


def test_excerpt_cuts_at_a_word():
    assert sanitize.excerpt("one two three four", 9) == "one two…"
    assert sanitize.excerpt("short", 20) == "short"
