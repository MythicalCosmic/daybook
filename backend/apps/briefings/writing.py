"""The words of a review, from its facts: the template (no AI) and the check of Claude's draft.

    content = template(facts, "uz")
    content, kept = checked(draft, facts, "uz")      # Claude's draft (apps.ai.agents.advisor)

A review's content is

    {"headline": "…",
     "sections": [{"key": "went_well", "title": "…", "bullets": ["…"], "facts": ["revenue"]},
                  {"key": "went_wrong", "title": "…", "bullets": ["…"], "facts": ["cash:low"]}],
     "actions": [{"text": "…", "fact": "cash:low", "label": "…", "url": "/c/12/finance/…"}]}

`facts` lists the signal each bullet rests on; `actions` are the (up to three) suggestions, each
tied to a signal and opening its page. Claude's draft keeps only what passes: a point or a
suggestion must cite a signal of the facts, a point must agree with the signal's tone (what went
well cites a good one), and every number in it must be a number of the facts
(apps.briefings.numbers). What falls out is filled from the template, so a review always reads
whole; `kept` says whether anything of Claude's stayed.
"""

from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.briefings import display, numbers
from apps.briefings import signals as signal_rules

SUGGESTIONS = 3
POINTS = 4
TEXT_MAX = 280
HEADLINE_MAX = 200
BOT_TEXT_MAX = 3500
# A bad signal this heavy is the headline (money running out, a loss, a critical alert);
# otherwise revenue is.
HEADLINE_WEIGHT = 20


class _Words:
    """The numbers of one review formatted for one language."""

    def __init__(self, facts: dict, language: str):
        self.facts = facts
        self.lang = display.lang_of(language)
        self.currency = facts.get("currency", "UZS")

    def money(self, value) -> str:
        return display.money(value, self.currency, self.lang)

    def pct(self, value) -> str:
        return display.percent(value, self.lang)

    def count(self, value) -> str:
        return display.number(value, self.lang)

    def day(self, value) -> str:
        return display.day(value, self.lang)

    def period(self) -> str:
        return display.period(self.facts["period"], self.lang)


# Points: one sentence per signal -----------------------------------------------------------------


def point(signal: dict, words: _Words) -> str:
    """The sentence of one signal, in the active language."""
    kind = signal["kind"]
    values = signal["values"]
    up = signal["tone"] == signal_rules.GOOD
    subject = signal.get("subject") or ""
    usual = values.get("vs_average_pct") is not None if isinstance(values, dict) else False
    if kind == "revenue":
        if usual:
            text = (
                _("Revenue grew to %(amount)s: %(pct)s above the usual level.")
                if up
                else _("Revenue fell to %(amount)s: %(pct)s below the usual level.")
            )
        else:
            text = (
                _("Revenue grew to %(amount)s: %(pct)s more than the period before.")
                if up
                else _("Revenue fell to %(amount)s: %(pct)s less than the period before.")
            )
        return text % {"amount": words.money(values["value"]), "pct": words.pct(values["move_pct"])}
    if kind == "gross_margin":
        text = (
            _("Gross margin rose to %(now)s (it was %(before)s).")
            if up
            else _("Gross margin fell to %(now)s (it was %(before)s).")
        )
        return text % {"now": words.pct(values["value"]), "before": words.pct(values["previous"])}
    if kind == "profit":
        text = (
            _("Profit grew to %(amount)s (usually %(usual)s).")
            if up
            else _("Profit fell to %(amount)s (usually %(usual)s).")
        )
        return text % {
            "amount": words.money(values["value"]),
            "usual": words.money(values["average"]),
        }
    if kind == "loss":
        return _("The period closed at a loss: %(amount)s.") % {
            "amount": words.money(abs_text(values["value"]))
        }
    if kind == "branch_loss":
        return _("%(branch)s: a loss of %(amount)s.") % {
            "branch": subject,
            "amount": words.money(abs_text(values["value"])),
        }
    if kind == "branch_margin":
        text = (
            _("%(branch)s: gross margin up to %(now)s (it was %(before)s).")
            if up
            else _("%(branch)s: gross margin down to %(now)s (it was %(before)s).")
        )
        return text % {
            "branch": subject,
            "now": words.pct(values["value"]),
            "before": words.pct(values["previous"]),
        }
    if kind == "expense_jump":
        if values.get("vs_average_pct") is None:
            return _("%(group)s: %(amount)s, a new expense this period.") % {
                "group": subject,
                "amount": words.money(values["value"]),
            }
        return _("%(group)s: %(amount)s, %(pct)s above the usual level (usually %(usual)s).") % {
            "group": subject,
            "amount": words.money(values["value"]),
            "pct": words.pct(values["vs_average_pct"]),
            "usual": words.money(values["average"]),
        }
    if kind == "payroll_share":
        text = (
            _("Staff costs took a smaller share of revenue: %(now)s (usually %(usual)s).")
            if up
            else _("Staff costs took %(now)s of revenue (usually %(usual)s).")
        )
        return text % {"now": words.pct(values["value"]), "usual": words.pct(values["average"])}
    if kind == "cash_below_zero":
        return _("Cash runs short: the forecast balance on %(date)s is %(amount)s.") % {
            "date": words.day(values["date"]),
            "amount": words.money(values["balance"]),
        }
    if kind == "cash_runway":
        days = values["runway_days"]
        return ngettext(
            "At the current pace the money lasts %(days)s day: the balance goes below zero on "
            "%(date)s.",
            "At the current pace the money lasts %(days)s days: the balance goes below zero on "
            "%(date)s.",
            days,
        ) % {"days": days, "date": words.day(values["below_zero_on"])}
    if kind == "cash_enough":
        days = values["horizon_days"]
        return ngettext(
            "There is money for the next %(days)s day: the lowest forecast balance is "
            "%(amount)s (%(date)s).",
            "There is money for the next %(days)s days: the lowest forecast balance is "
            "%(amount)s (%(date)s).",
            days,
        ) % {
            "days": days,
            "amount": words.money(values["low_balance"]),
            "date": words.day(values["low_date"]),
        }
    if kind == "receivables_overdue":
        return _("Overdue customer debts: %(count)s, %(amount)s in all.") % {
            "count": values["overdue_count"],
            "amount": words.money(values["overdue"]),
        }
    if kind == "payables_overdue":
        return _("Overdue payments to distributors: %(count)s, %(amount)s in all.") % {
            "count": values["overdue_count"],
            "amount": words.money(values["overdue"]),
        }
    if kind == "average_receipt":
        if usual:
            text = (
                _("The average receipt rose to %(amount)s: %(pct)s above the usual level.")
                if up
                else _("The average receipt fell to %(amount)s: %(pct)s below the usual level.")
            )
        else:
            text = (
                _("The average receipt rose to %(amount)s: %(pct)s more than the period before.")
                if up
                else _(
                    "The average receipt fell to %(amount)s: %(pct)s less than the period before."
                )
            )
        return text % {"amount": words.money(values["value"]), "pct": words.pct(values["move_pct"])}
    if kind == "receipts":
        if usual:
            text = (
                _("Receipts: %(count)s, %(pct)s more than usual.")
                if up
                else _("Receipts: %(count)s, %(pct)s fewer than usual.")
            )
        else:
            text = (
                _("Receipts: %(count)s, %(pct)s more than the period before.")
                if up
                else _("Receipts: %(count)s, %(pct)s fewer than the period before.")
            )
        return text % {"count": words.count(values["value"]), "pct": words.pct(values["move_pct"])}
    if kind == "cash_difference":
        return _("The shifts came up short in cash: %(amount)s.") % {
            "amount": words.money(abs_text(values["cash_difference"]))
        }
    if kind == "slow_stock":
        days = values["days_of_cover"]
        return ngettext(
            "%(item)s: at the recent pace the stock lasts %(days)s day.",
            "%(item)s: at the recent pace the stock lasts %(days)s days.",
            days,
        ) % {"item": subject, "days": days}
    if kind == "dead_stock":
        return ngettext(
            "%(item)s: no sales in %(days)s day, %(quantity)s on hand.",
            "%(item)s: no sales in %(days)s days, %(quantity)s on hand.",
            values["velocity_days"],
        ) % {
            "item": subject,
            "days": values["velocity_days"],
            "quantity": words.count(values["quantity"]),
        }
    if kind == "expiring":
        days = values["within_days"]
        if values.get("value") is not None:
            return ngettext(
                "Batches expiring within %(days)s day: %(count)s, worth %(amount)s.",
                "Batches expiring within %(days)s days: %(count)s, worth %(amount)s.",
                days,
            ) % {"days": days, "count": values["count"], "amount": words.money(values["value"])}
        return ngettext(
            "Batches expiring within %(days)s day: %(count)s.",
            "Batches expiring within %(days)s days: %(count)s.",
            days,
        ) % {"days": days, "count": values["count"]}
    if kind == "late_more":
        return _("Late arrivals: %(count)s (usually %(usual)s).") % {
            "count": values["value"],
            "usual": words.count(values["usual"]),
        }
    if kind == "late_fewer":
        return _("Fewer late arrivals: %(count)s (usually %(usual)s).") % {
            "count": values["value"],
            "usual": words.count(values["usual"]),
        }
    if kind == "leavers":
        return _("Left the team: %(names)s.") % {"names": ", ".join(values["names"])}
    if kind == "insight":
        return _("Open alert: %(title)s") % {"title": values["title"]}
    return subject


def abs_text(value) -> str:
    text = str(value)
    return text[1:] if text.startswith("-") else text


# Suggestions: what to do about a signal -------------------------------------------------------


def suggestion(signal: dict, words: _Words) -> str | None:
    """What to do about one signal (None: nothing to suggest, e.g. a good one)."""
    kind = signal["kind"]
    values = signal["values"]
    subject = signal.get("subject") or ""
    bad = signal["tone"] == signal_rules.BAD
    if not bad:
        return None
    if kind == "cash_below_zero":
        return _(
            "Plan the cash for %(date)s: move a payment to a distributor or collect what "
            "customers owe before then."
        ) % {"date": words.day(values["date"])}
    if kind == "cash_runway":
        return _(
            "Cut spending or bring money in sooner: on %(date)s the balance goes below zero."
        ) % {"date": words.day(values["below_zero_on"])}
    if kind == "receivables_overdue":
        return _("Call the customers who owe %(amount)s past due and agree on payment dates.") % {
            "amount": words.money(values["overdue"])
        }
    if kind == "payables_overdue":
        return _("Agree new dates with the distributors for %(amount)s of overdue payments.") % {
            "amount": words.money(values["overdue"])
        }
    if kind == "branch_margin":
        return _(
            "%(branch)s: check purchase prices and discounts, the gross margin is %(now)s now."
        ) % {"branch": subject, "now": words.pct(values["value"])}
    if kind == "branch_loss":
        return _("%(branch)s: go through its costs line by line, the loss is %(amount)s.") % {
            "branch": subject,
            "amount": words.money(abs_text(values["value"])),
        }
    if kind == "expense_jump":
        if values.get("vs_average_pct") is None:
            return _("%(group)s: find out what this new %(amount)s was for.") % {
                "group": subject,
                "amount": words.money(values["value"]),
            }
        return _("%(group)s: look into it, %(amount)s against %(usual)s usually.") % {
            "group": subject,
            "amount": words.money(values["value"]),
            "usual": words.money(values["average"]),
        }
    if kind == "payroll_share":
        return _("Check overtime and the roster: staff costs took %(now)s of revenue.") % {
            "now": words.pct(values["value"])
        }
    if kind == "revenue":
        return _(
            "Find out why revenue fell: check the out-of-stock list (defektura) and the opening "
            "hours."
        )
    if kind == "gross_margin":
        return _("Compare purchase prices with the weeks before and review the markups.")
    if kind in ("loss", "profit"):
        return _("Go through the period's costs, the biggest groups first.")
    if kind in ("average_receipt", "receipts"):
        return _("Check what was out of stock and how the prices compare.")
    if kind == "cash_difference":
        return _("Check the shifts with cash differences and talk to the cashiers.")
    if kind == "slow_stock":
        return _("%(item)s: order less, or move part of it to another pharmacy.") % {
            "item": subject
        }
    if kind == "dead_stock":
        return _(
            "%(item)s: move it to a pharmacy where it sells, or return it to the distributor."
        ) % {"item": subject}
    if kind == "expiring":
        return ngettext(
            "Sell or move first the batches that expire within %(days)s day.",
            "Sell or move first the batches that expire within %(days)s days.",
            values["within_days"],
        ) % {"days": values["within_days"]}
    if kind == "late_more":
        return _("Talk to the team about lateness: %(count)s late arrivals.") % {
            "count": values["value"]
        }
    if kind == "leavers":
        return _("Plan the shifts without the people who left, and start hiring if needed.")
    if kind == "insight":
        return values.get("suggested_action") or (
            _("Look at the alert: %(title)s") % {"title": values["title"]}
        )
    return None


def action_label(signal: dict) -> str:
    kind = signal["kind"]
    if kind.startswith("cash_"):
        return _("Open the cash plan")
    if kind in ("receivables_overdue", "payables_overdue"):
        return _("Open the debts")
    if kind in ("branch_margin", "branch_loss"):
        return _("Open the pharmacy's report")
    if kind == "expense_jump":
        return _("Open the expense")
    if kind in ("slow_stock", "dead_stock"):
        return _("Open the stock")
    if kind == "expiring":
        return _("Open expiry dates")
    if kind in ("late_more", "late_fewer"):
        return _("Open attendance")
    if kind == "leavers":
        return _("Open the team")
    if kind in ("average_receipt", "receipts", "cash_difference"):
        return _("Open sales")
    if kind == "insight":
        return _("Open the alert")
    return _("Open the report")


# The headline ------------------------------------------------------------------------------------


def _revenue_line(facts: dict, words: _Words) -> str | None:
    monthly = facts.get("kind") == "monthly"
    figure = None
    if "finance" in facts and facts["finance"]["revenue"]["value"] != "0.00":
        figure = facts["finance"]["revenue"]
    elif "sales" in facts:
        figure = facts["sales"]["net"]
    if figure is None:
        return None
    values = {"period": words.period(), "amount": words.money(figure["value"])}
    move = figure.get("change_pct")
    if move is None or move in ("0.0", "-0.0"):
        text = (
            _("%(period)s: revenue %(amount)s.")
            if monthly
            else _("Week of %(period)s: revenue %(amount)s.")
        )
        return text % values
    values["pct"] = words.pct(move)
    if move.startswith("-"):
        text = (
            _("%(period)s: revenue %(amount)s, down %(pct)s on the month before.")
            if monthly
            else _("Week of %(period)s: revenue %(amount)s, down %(pct)s on the week before.")
        )
    else:
        text = (
            _("%(period)s: revenue %(amount)s, up %(pct)s on the month before.")
            if monthly
            else _("Week of %(period)s: revenue %(amount)s, up %(pct)s on the week before.")
        )
    return text % values


def headline(facts: dict, words: _Words) -> str:
    found = facts.get("signals") or []
    heavy = next(
        (s for s in found if s["tone"] == signal_rules.BAD and s["weight"] >= HEADLINE_WEIGHT),
        None,
    )
    if heavy is not None:
        return point(heavy, words)
    line = _revenue_line(facts, words)
    if line:
        return line
    if found:
        return point(found[0], words)
    if facts.get("kind") == "monthly":
        return _("%(period)s: nothing unusual.") % {"period": words.period()}
    return _("Week of %(period)s: nothing unusual.") % {"period": words.period()}


# Putting it together ---------------------------------------------------------------------------


def _titles() -> dict[str, str]:
    return {"went_well": _("What went well"), "went_wrong": _("What went wrong")}


def _sections(points: dict[str, list[tuple[str, str]]]) -> list[dict]:
    titles = _titles()
    return [
        {
            "key": key,
            "title": titles[key],
            "bullets": [text for text, _fact in points[key]],
            "facts": [fact for _text, fact in points[key]],
        }
        for key in ("went_well", "went_wrong")
    ]


def _action(text: str, signal: dict) -> dict:
    return {
        "text": text,
        "fact": signal["key"],
        "label": action_label(signal),
        "url": signal["url"],
    }


def template(facts: dict, language: str) -> dict:
    """The review written from the rules: the heaviest good and bad signals as points, a
    suggestion for each of the heaviest bad ones."""
    with translation.override(display.lang_of(language)):
        words = _Words(facts, language)
        found = facts.get("signals") or []
        points = {"went_well": [], "went_wrong": []}
        for signal in found:
            key = "went_well" if signal["tone"] == signal_rules.GOOD else "went_wrong"
            if len(points[key]) < POINTS:
                points[key].append((point(signal, words), signal["key"]))
        actions = []
        for signal in found:
            if len(actions) >= SUGGESTIONS:
                break
            if text := suggestion(signal, words):
                actions.append(_action(text, signal))
        return {
            "headline": headline(facts, words),
            "sections": _sections(points),
            "actions": actions,
        }


def _clean(text, limit: int = TEXT_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def checked(draft: dict, facts: dict, language: str) -> tuple[dict, bool]:
    """Claude's draft (`{headline, went_well, went_wrong, suggestions}`, each item `{text,
    fact}`) with what doesn't hold taken out and the gaps filled from the template; and whether
    anything of Claude's stayed."""
    known = numbers.known_numbers(facts)
    found = signal_rules.by_key(facts)
    fallback = template(facts, language)
    kept = False

    title = _clean(draft.get("headline"), HEADLINE_MAX)
    if title and numbers.numbers_ok(title, known):
        kept = True
    else:
        title = fallback["headline"]

    points: dict[str, list[tuple[str, str]]] = {}
    for key, tone in (("went_well", signal_rules.GOOD), ("went_wrong", signal_rules.BAD)):
        chosen = []
        for item in draft.get(key) or []:
            text = _clean(item.get("text"))
            signal = found.get(str(item.get("fact") or ""))
            if not text or signal is None or signal["tone"] != tone:
                continue
            if not numbers.numbers_ok(text, known) or signal["key"] in {f for _t, f in chosen}:
                continue
            chosen.append((text, signal["key"]))
        if chosen:
            kept = True
        else:
            section = next(s for s in fallback["sections"] if s["key"] == key)
            chosen = list(zip(section["bullets"], section["facts"], strict=True))
        points[key] = chosen[:POINTS]

    with translation.override(display.lang_of(language)):
        actions = []
        for item in draft.get("suggestions") or []:
            text = _clean(item.get("text"))
            signal = found.get(str(item.get("fact") or ""))
            if not text or signal is None or not numbers.numbers_ok(text, known):
                continue
            if signal["key"] in {action["fact"] for action in actions}:
                continue
            actions.append(_action(text, signal))
            if len(actions) == SUGGESTIONS:
                break
        if actions:
            kept = True
        for action in fallback["actions"]:
            if len(actions) >= SUGGESTIONS:
                break
            if action["fact"] not in {row["fact"] for row in actions}:
                actions.append(action)
        sections = _sections(points)
    return {"headline": title, "sections": sections, "actions": actions}, kept


# What the owner bot sends -------------------------------------------------------------------------


def title(facts: dict, language: str) -> str:
    with translation.override(display.lang_of(language)):
        shown = display.period(facts["period"], language)
        if facts.get("kind") == "monthly":
            return _("Monthly business review: %(period)s") % {"period": shown}
        return _("Weekly business review: %(period)s") % {"period": shown}


def bot_text(content: dict, language: str, kind: str = "weekly") -> str:
    """The review as plain text for Telegram: the headline, the two lists, the suggestions."""
    with translation.override(display.lang_of(language)):
        lines = [content.get("headline", "")]
        for section in content.get("sections") or []:
            if section.get("bullets"):
                lines += ["", section["title"]]
                lines += [f"- {bullet}" for bullet in section["bullets"]]
        actions = content.get("actions") or []
        if actions:
            todo = _("What to do this month") if kind == "monthly" else _("What to do this week")
            lines += ["", todo]
            lines += [f"{index}. {action['text']}" for index, action in enumerate(actions, 1)]
        text = "\n".join(lines).strip()
        # A Telegram message holds 4096 characters (the title and the button come on top).
        while len(text) > BOT_TEXT_MAX and "\n" in text:
            text = text.rsplit("\n", 1)[0].rstrip()
        return text[:BOT_TEXT_MAX]
