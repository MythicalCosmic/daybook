"""Golden tests of the seven kinds of question (docs/PLAN-LEARNING.md §4.3): validation of
`data`, what is shown, the answer shapes, full and partial credit, the text normalisation."""

import random
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from apps.learning import grading
from apps.learning.grading import Grade, InvalidAnswer, InvalidQuestion, grade

SINGLE = {
    "options": [
        {"id": "a", "text": "+2 °C dan +8 °C gacha", "correct": True},
        {"id": "b", "text": "0 °C dan +4 °C gacha", "correct": False},
        {"id": "c", "text": "+15 °C dan +25 °C gacha", "correct": False},
    ]
}
MULTI = {
    "options": [
        {"id": "a", "text": "Insulin", "correct": True},
        {"id": "b", "text": "Paratsetamol tabletkasi", "correct": False},
        {"id": "c", "text": "Vaksina", "correct": True},
        {"id": "d", "text": "Vitamin C", "correct": False},
    ]
}
TRUE_FALSE = {"answer": False}
ORDER = {
    "items": [
        {"id": "a", "text": "Nakladnoyni sanash"},
        {"id": "b", "text": "Seriya va muddatni tekshirish"},
        {"id": "c", "text": "Muzlatgichga qo‘yish"},
        {"id": "d", "text": "Nakladnoyni ilovaga yuklash"},
    ]
}
MATCH = {
    "pairs": [
        {"id": "a", "left": "XPN", "right": "Ta’sir etuvchi modda"},
        {"id": "b", "left": "Defektura", "right": "Topilmagan dori so‘rovi"},
        {"id": "c", "left": "Nakladnoy", "right": "Yuk xati"},
    ]
}
TEXT = {"answers": ["2–8", "+2 – +8"], "case": False}
NUMBER = {"value": 4.5, "tolerance": 0.1, "unit": "ml"}


def shown(kind, data, seed=1):
    return grading.shown_order(kind, data, shuffle=True, rng=random.Random(seed))


def score(kind, data, order, answer, partial=True) -> Fraction:
    return grade(kind, data, order, answer, partial=partial).share


# single ------------------------------------------------------------------------------------


@pytest.mark.parametrize("partial", [True, False])
def test_single_scores_the_right_option_only(partial):
    order = shown("single", SINGLE)
    assert score("single", SINGLE, order, {"option": "a"}, partial) == 1
    assert score("single", SINGLE, order, {"option": "b"}, partial) == 0
    assert grade("single", SINGLE, order, None, partial=partial) == Grade(Fraction(0), False)


def test_single_needs_exactly_one_right_option_and_two_to_six():
    with pytest.raises(InvalidQuestion) as two_right:
        grading.clean_data(
            "single",
            {
                "options": [
                    {"text": "A", "correct": True},
                    {"text": "B", "correct": True},
                ]
            },
        )
    assert "data.options" in two_right.value.errors
    with pytest.raises(InvalidQuestion) as one_only:
        grading.clean_data("single", {"options": [{"text": "A", "correct": True}]})
    assert one_only.value.errors["data.options"] == ["How many: 2–6."]
    with pytest.raises(InvalidQuestion):
        grading.clean_data(
            "single", {"options": [{"text": str(n), "correct": n == 0} for n in range(7)]}
        )


# multi -------------------------------------------------------------------------------------


def test_multi_full_points_only_for_exactly_the_right_set():
    order = shown("multi", MULTI)
    assert score("multi", MULTI, order, {"options": ["c", "a"]}) == 1
    assert score("multi", MULTI, order, {"options": ["a", "c"]}, partial=False) == 1


@pytest.mark.parametrize(
    ("picked", "partial_share"),
    [
        (["a"], Fraction(1, 2)),  # one of two right, nothing wrong
        (["a", "b"], Fraction(0)),  # one right, one wrong: (1 - 1) / 2
        (["a", "c", "b"], Fraction(1, 2)),  # both right and one wrong: (2 - 1) / 2
        (["b", "d"], Fraction(0)),  # max(0, (0 - 2) / 2)
    ],
)
def test_multi_partial_credit(picked, partial_share):
    order = shown("multi", MULTI)
    assert score("multi", MULTI, order, {"options": picked}, partial=True) == partial_share
    assert score("multi", MULTI, order, {"options": picked}, partial=False) == 0


def test_multi_with_nothing_picked_is_unanswered():
    order = shown("multi", MULTI)
    assert grade("multi", MULTI, order, {"options": []}, partial=True).answered is False


def test_multi_needs_a_right_option():
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data("multi", {"options": [{"text": "A"}, {"text": "B"}]})
    assert found.value.errors["data.options"] == ["Mark at least one option as right."]


# true / false --------------------------------------------------------------------------------


@pytest.mark.parametrize("partial", [True, False])
def test_true_false(partial):
    assert score("true_false", TRUE_FALSE, [], {"value": False}, partial) == 1
    assert score("true_false", TRUE_FALSE, [], {"value": True}, partial) == 0
    with pytest.raises(InvalidAnswer):
        grading.clean_answer("true_false", TRUE_FALSE, [], {"value": "no"})


def test_true_false_needs_a_boolean():
    with pytest.raises(InvalidQuestion):
        grading.clean_data("true_false", {"answer": "true"})
    assert grading.clean_data("true_false", {"answer": True, "extra": 1}) == {"answer": True}


# order -------------------------------------------------------------------------------------


def as_shown(order, real_ids):
    """The answer that lists `real_ids` in that order, in the ids the person was shown."""
    return {"order": [f"o{order.index(value) + 1}" for value in real_ids]}


def test_order_is_always_shuffled_and_shown_with_ids_by_place():
    for seed in range(30):
        order = grading.shown_order("order", ORDER, shuffle=False, rng=random.Random(seed))
        assert order != ["a", "b", "c", "d"]
        question = SimpleNamespace(pk=7, kind="order", text="Kirim tartibi", points=2, data=ORDER)
        options = grading.play(question, order)["options"]
        assert [option["id"] for option in options] == ["o1", "o2", "o3", "o4"]


def test_order_full_and_partial_credit():
    order = ["c", "a", "d", "b"]
    assert score("order", ORDER, order, as_shown(order, ["a", "b", "c", "d"])) == 1
    # a and d in place, b and c swapped: half the steps in their right place.
    swapped = as_shown(order, ["a", "c", "b", "d"])
    assert score("order", ORDER, order, swapped, partial=True) == Fraction(1, 2)
    assert score("order", ORDER, order, swapped, partial=False) == 0
    # The order as shown is never right.
    assert score("order", ORDER, order, {"order": ["o1", "o2", "o3", "o4"]}, partial=False) == 0


def test_order_needs_a_whole_order_and_three_to_eight_steps():
    with pytest.raises(InvalidAnswer):
        grading.clean_answer("order", ORDER, ["c", "a", "d", "b"], {"order": ["o1", "o2"]})
    with pytest.raises(InvalidQuestion):
        grading.clean_data("order", {"items": [{"text": "A"}, {"text": "B"}]})


# match -------------------------------------------------------------------------------------


def test_match_shows_the_left_as_written_and_the_right_shuffled_under_new_ids():
    for seed in range(30):
        order = shown("match", MATCH, seed)
        assert order != ["a", "b", "c"]
        question = SimpleNamespace(pk=8, kind="match", text="Juftlang", points=3, data=MATCH)
        play = grading.play(question, order)
        assert [row["text"] for row in play["left"]] == ["XPN", "Defektura", "Nakladnoy"]
        assert [row["id"] for row in play["left"]] == ["l1", "l2", "l3"]
        assert [row["id"] for row in play["right"]] == ["r1", "r2", "r3"]


def test_match_full_and_partial_credit():
    order = ["c", "a", "b"]  # r1 = Yuk xati, r2 = Ta’sir etuvchi modda, r3 = Topilmagan dori
    right = {"pairs": {"l1": "r2", "l2": "r3", "l3": "r1"}}
    assert score("match", MATCH, order, right) == 1
    one_wrong_pair = {"pairs": {"l1": "r2", "l2": "r1", "l3": "r3"}}
    assert score("match", MATCH, order, one_wrong_pair, partial=True) == Fraction(1, 3)
    assert score("match", MATCH, order, one_wrong_pair, partial=False) == 0
    two_of_three = {"pairs": {"l1": "r2", "l2": "r3"}}
    assert score("match", MATCH, order, two_of_three, partial=True) == Fraction(2, 3)


def test_match_needs_two_to_six_pairs_with_both_sides():
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data("match", {"pairs": [{"left": "A", "right": ""}, {"left": "B"}]})
    assert set(found.value.errors) == {"data.pairs.0.right", "data.pairs.1.right"}


# text --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed",
    [
        "2-8",
        "2–8",
        " 2 — 8 ",
        "2 - 8 °C",
        "2°C - 8°C",
        "2-8 C",
        "2‒8℃",
        "+2 – +8",
        "2-8.",
    ],
)
def test_text_accepts_the_answer_however_it_is_typed(typed):
    assert score("text", TEXT, [], {"text": typed}) == 1


@pytest.mark.parametrize("typed", ["2-9", "28", "2 8", "sakkiz"])
def test_text_refuses_another_answer(typed):
    assert score("text", TEXT, [], {"text": typed}) == 0


def test_text_ignores_case_and_unifies_the_apostrophes():
    data = {"answers": ["Ko‘k terak"], "case": False}
    for typed in ["ko'k  terak", "KOʻK TERAK", "ko`k terak", "Ko’k terak"]:
        assert score("text", data, [], {"text": typed}) == 1


def test_text_with_case_kept():
    data = {"answers": ["XPN"], "case": True}
    assert score("text", data, [], {"text": "XPN"}) == 1
    assert score("text", data, [], {"text": "xpn"}) == 0


def test_text_needs_an_accepted_answer():
    with pytest.raises(InvalidQuestion):
        grading.clean_data("text", {"answers": []})
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data("text", {"answers": ["°C"]})
    assert "data.answers.0" in found.value.errors
    assert grading.clean_data("text", {"answers": ["2-8", "2–8", "2 - 8"]}) == {
        "answers": ["2-8"],
        "case": False,
    }


# number ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "share"),
    [(4.5, 1), (4.6, 1), (4.4, 1), ("4,55", 1), (" 4.5 ", 1), (4.61, 0), (5, 0), (4, 0)],
)
def test_number_within_the_tolerance(typed, share):
    assert score("number", NUMBER, [], {"value": typed}) == share


def test_number_compares_exactly_not_in_floating_point():
    data = {"value": 0.3, "tolerance": 0.1, "unit": ""}
    assert score("number", data, [], {"value": 0.4}) == 1  # 0.4 - 0.3 is 0.1000…04 in floats
    assert score("number", {"value": 8, "tolerance": 0}, [], {"value": 8}) == 1


def test_number_needs_a_value_and_a_tolerance_of_zero_or_more():
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data("number", {"value": "abc", "tolerance": -1})
    assert set(found.value.errors) == {"data.value", "data.tolerance"}
    assert grading.clean_data("number", {"value": "36,6", "unit": " °C "}) == {
        "value": 36.6,
        "tolerance": 0,
        "unit": "°C",
    }
    with pytest.raises(InvalidAnswer):
        grading.clean_answer("number", NUMBER, [], {"value": "four"})


# Shared rules ----------------------------------------------------------------------------------


def test_ids_are_filled_in_and_must_be_unique():
    data = grading.clean_data(
        "single",
        {"options": [{"text": "A", "correct": True}, {"id": "a", "text": "B"}, {"text": "C"}]},
    )
    assert [option["id"] for option in data["options"]] == ["b", "a", "c"]
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data(
            "single",
            {"options": [{"id": "x", "text": "A", "correct": True}, {"id": "x", "text": "B"}]},
        )
    assert "data.options.1.id" in found.value.errors


def test_texts_are_trimmed_not_empty_and_at_most_300():
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data(
            "single",
            {"options": [{"text": " ", "correct": True}, {"text": "x" * 301}]},
        )
    assert found.value.errors["data.options.0.text"] == ["Write something here."]
    assert found.value.errors["data.options.1.text"] == ["Keep it under 300 characters."]
    with pytest.raises(InvalidQuestion):
        grading.clean_data(
            "single", {"options": [{"text": "Bir", "correct": True}, {"text": " bir "}]}
        )


def test_an_unknown_kind_is_refused():
    with pytest.raises(InvalidQuestion) as found:
        grading.clean_data("essay", {})
    assert set(found.value.errors) == {"kind"}


PLAY_KEYS = {"id", "kind", "text", "image_url", "points", "options", "left", "right", "unit"}
ALL_KINDS = [
    ("single", SINGLE),
    ("multi", MULTI),
    ("true_false", TRUE_FALSE),
    ("order", ORDER),
    ("match", MATCH),
    ("text", TEXT),
    ("number", NUMBER),
]


@pytest.mark.parametrize(("kind", "data"), ALL_KINDS)
def test_what_is_shown_never_holds_the_answer(kind, data):
    order = shown(kind, data)
    question = SimpleNamespace(pk=1, kind=kind, text="?", points=1, data=data)
    play = grading.play(question, order)
    assert set(play) == PLAY_KEYS
    for row in play["options"] + play["left"] + play["right"]:
        assert set(row) == {"id", "text"}
    assert play["unit"] == ("ml" if kind == "number" else None)
    for secret in ("2–8", "+2 – +8", "4.5"):
        assert secret not in str(play)


@pytest.mark.parametrize(("kind", "data"), ALL_KINDS)
def test_the_right_answer_scores_full_points(kind, data):
    order = shown(kind, data)
    right = grading.right_answer(kind, data, order)
    assert grade(kind, data, order, right, partial=False) == Grade(Fraction(1), True)


def test_a_question_changed_after_the_draw_still_grades():
    order = ["c", "a", "b"]
    changed = {"options": [*SINGLE["options"][:2], {"id": "e", "text": "Yangi", "correct": False}]}
    assert grading.reconcile("single", changed, order) == ["a", "b", "e"]
    assert score("single", changed, order, {"option": "a"}) == 1
    assert score("single", changed, order, {"option": "c"}) == 0  # gone: no answer


def test_the_score_is_floored_to_a_percent():
    grades = [(1, Grade(Fraction(1), True)), (2, Grade(Fraction(1, 3), True)), (3, grading.NOTHING)]
    found = grading.total(grades)
    assert found.score == Decimal("1.67")
    assert found.max_score == Decimal("6.00")
    assert found.percent == 27  # (1 + 2/3) / 6 = 27.7 %
    assert grading.share_decimal(Fraction(2, 3)) == Decimal("0.667")
