"""Telegram's HTML subset and its limits, as the bots and the backend apply them."""

from aiogram import html

from apps.notifications.html_limits import (
    CAPTION_LIMIT,
    TEXT_LIMIT,
    fit,
    problems,
    visible_length,
)


def test_tags_do_not_count_and_an_entity_is_one_character():
    assert visible_length("<b>Kassa</b> &amp; ombor") == len("Kassa & ombor")
    assert visible_length('<a href="tg://user?id=1">Ali</a>') == 3


def test_length_is_counted_in_utf16_units_like_telegram():
    assert visible_length("o‘g‘il") == 6
    assert visible_length("𝐀") == 2  # outside the BMP: two units


def test_a_text_that_fits_is_left_alone():
    text = "<b>Muzlatgich</b>\n2–8 °C"

    assert fit(text, CAPTION_LIMIT) == text


def test_a_long_text_is_cut_at_a_line_end_with_its_tags_closed():
    lines = [f"<b>Qator {n}</b> " + "x" * 50 for n in range(200)]
    text = "<blockquote>" + "\n".join(lines) + "</blockquote>"

    cut = fit(text, CAPTION_LIMIT)

    assert visible_length(cut) <= CAPTION_LIMIT
    assert problems(cut) == []
    assert cut.endswith("</blockquote>…")
    assert "\n<b>Qator" in cut and cut.count("<b>") == cut.count("</b>")


def test_a_long_line_is_cut_between_characters_never_inside_a_tag_or_entity():
    text = "<i>" + "&amp;" * 5000 + "</i>"

    cut = fit(text, TEXT_LIMIT)

    assert visible_length(cut) == TEXT_LIMIT
    assert problems(cut) == []
    assert cut.endswith("&amp;</i>…")


def test_quoted_user_text_has_no_problems():
    title = "Harorat < 8 °C & <b>tekshiring</b>"

    assert problems(f"<b>{html.quote(title)}</b>") == []


def test_unescaped_user_text_is_reported():
    assert problems("Harorat < 8 °C")[0].startswith("unescaped '<'")
    assert problems("Ali & Vali")[0].startswith("unescaped '&'")
    assert problems("<b>Ali <Vali></b>")[0].startswith("unsupported tag <vali>")
    assert problems("<b>open")[0] == "left open: b"
    assert problems("<i>a</b></i>")[0] == "</b> at 4 closes nothing open"
    assert problems("x" * 5, limit=4) == ["5 characters, more than 4"]
