"""Uzbekistan's tax deadlines and rates (v12, the tax calendar `apps.finance.taxes`): one data
module, so a change in the law is a one-line edit here.

Read on 12.11.2026 in the consolidated Tax Code on lex.uz (Russian https://lex.uz/ru/docs/4674893,
Uzbek, the official text, https://lex.uz/docs/4674902; the edition in force on that day, including
ZRU-1104 and ZRU-1108 of 25.12.2025) and the decrees cited per rule. "H": read in the primary text;
"M": a secondary source or the primary text is silent. Every product screen says "Check with your
accountant": these are general rules, a company's own case can differ.

Each `Rule` is one deadline that comes back every period:
    key           stored on `TaxMark.tax` (never rename a key that is in use)
    tax           which tax it belongs to (`TAXES`), for the estimate and the names
    period        "month", "quarter" or "year": the period it is for
    action        "file_pay" (return and payment on the same day), "file" or "pay"
    anchor, months, day
                  the due date: `day` of the month `months` after the period's last month
                  (anchor "end") or its first month (anchor "start"); `january_day` overrides it
                  for January
    regimes       the tax regimes it applies to (`FinanceSettings.TaxRegime` values)
    needs         "" (always), "payroll" (the company pays people), "property" (owns premises),
                  "land" (holds land), "big_income" (last year's income over 20 bn so‘m)
    quarters      for quarterly rules, which quarters (the fourth is the year's return)
    law, url      where it is written
    valid_from    since when (a rule replaced later gets `valid_to` and a new line)

Deadlines on a day off move to the next working day: Tax Code art. 5 («Если последний день срока
приходится на день, признаваемый … выходным и (или) нерабочим днем, днем окончания срока считается
рабочий день, следующий за выходным», H).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

CODE_RU = "https://lex.uz/ru/docs/4674893"
CODE_UZ = "https://lex.uz/docs/4674902"
UP_100 = "https://lex.uz/ru/docs/8237115"  # Decree UP-100 of 26.05.2026
UP_115 = "https://lex.uz/docs/8283656"  # Decree UP-115 of 23.06.2026
INPS_RULES = "https://lex.uz/docs/7231786"  # Regulation reg. No. 3577 of 20.11.2024

VAT = "vat"
VAT_SIMPLIFIED = "vat_simplified"
TURNOVER = "turnover"
ALL_REGIMES = (TURNOVER, VAT, VAT_SIMPLIFIED)
VAT_PAYERS = (VAT, VAT_SIMPLIFIED)


@dataclass(frozen=True)
class Tax:
    key: str
    name: object  # lazy text
    rate: Decimal | None  # per cent, None: no single rate
    rate_law: str


# The taxes and their rates.
TAXES: dict[str, Tax] = {
    tax.key: tax
    for tax in (
        # Art. 258 part 1: «налоговая ставка устанавливается в размере 12 процентов» (H).
        Tax("vat", _("VAT (QQS)"), Decimal(12), "Tax Code art. 258"),
        # UP-100 item 6(a): «6 процентов относительно всех оборотов», from 01.06.2026 to
        # 01.01.2030, optional, for trade, catering and services; no input VAT credit (item
        # 6(c)), profit tax 0 % and no profit-tax return (item 6(b)) (H).
        Tax("vat_simplified", _("Simplified VAT 6 %"), Decimal(6), "Decree UP-100, item 6"),
        # Art. 467 part 1 (ZRU-1108): 4 % general rate; retail 4 % in cities of 100 000+, 2 %
        # elsewhere, 1 % in remote areas (H). The company's own rate is a setting.
        Tax("turnover", _("Turnover tax"), Decimal(4), "Tax Code art. 467"),
        # Art. 337 part 1 item 12: 15 % for other taxpayers (H).
        Tax("profit", _("Profit tax"), Decimal(15), "Tax Code art. 337"),
        # Art. 381: 12 % (H). The 0.1 % pension contribution (INPS) is inside it, not on top:
        # art. 385 part 7 «Исчисленная сумма налога уменьшается на сумму обязательных
        # ежемесячных взносов на индивидуальные накопительные пенсионные счета» (H); the
        # 0.1 % rate itself is from secondary sources (M).
        Tax("income_tax", _("Personal income tax (JShDS)"), Decimal(12), "Tax Code art. 381"),
        # Art. 405 item 1: 12 % for ordinary taxpayers (H).
        Tax("social_tax", _("Social tax"), Decimal(12), "Tax Code art. 405"),
        # Art. 415 part 1: 1.5 % of the property's average annual residual value (H).
        Tax("property", _("Property tax"), Decimal("1.5"), "Tax Code art. 415"),
        # Art. 429: fixed amounts per hectare by region and zone (H).
        Tax("land", _("Land tax"), None, "Tax Code art. 429"),
    )
}


@dataclass(frozen=True)
class Rule:
    key: str
    tax: str
    name: object  # lazy text: what the deadline is
    period: str
    action: str
    anchor: str
    months: int
    day: int
    regimes: tuple[str, ...]
    law: str
    url: str
    valid_from: date
    needs: str = ""
    quarters: tuple[int, ...] = (1, 2, 3, 4)
    january_day: int | None = None
    valid_to: date | None = None
    confidence: str = "H"
    note: object = ""  # lazy text shown with the deadline


CODE_2020 = date(2020, 1, 1)  # the Tax Code's edition in force since 01.01.2020

RULES: tuple[Rule, ...] = (
    # VAT: period a month (art. 259); return «не позднее двадцатого числа месяца, следующего за
    # истекшим налоговым периодом» (art. 273 part 1), payment «не позднее срока представления
    # налоговой отчетности» (art. 273 part 2) (H).
    Rule(
        "vat", "vat", _("VAT return and payment"), "month", "file_pay", "end", 1, 20,
        (VAT,), "Tax Code arts. 259, 273", CODE_RU, CODE_2020,
    ),
    # Simplified VAT 6 %: neither UP-100 nor the Code sets its period or days yet; by analogy
    # with VAT (art. 273), monthly by the 20th (M).
    Rule(
        "vat_simplified", "vat_simplified", _("Simplified VAT return and payment"), "month",
        "file_pay", "end", 1, 20, (VAT_SIMPLIFIED,), "Decree UP-100; Tax Code art. 273", UP_100,
        date(2026, 6, 1), confidence="M",
        note=_("The decree sets no day of its own yet: the VAT day is shown."),
    ),
    # Turnover tax: tax period a year, reporting period a month (art. 469); the month's return
    # «не позднее пятнадцатого числа месяца, следующего за отчетным периодом», the year's «не
    # позднее 15 февраля» (art. 470 part 3); payment by the same days (art. 470 part 5) (H).
    Rule(
        "turnover", "turnover", _("Turnover tax return and payment"), "month", "file_pay", "end",
        1, 15, (TURNOVER,), "Tax Code arts. 469, 470", CODE_RU, date(2026, 1, 1),
    ),
    Rule(
        "turnover_year", "turnover", _("Turnover tax: the year's return"), "year", "file", "end",
        2, 15, (TURNOVER,), "Tax Code art. 470", CODE_RU, date(2026, 1, 1),
    ),
    # Profit tax: reporting period a quarter (art. 338); the quarter's return by the 20th of the
    # month after it, the year's «не позднее 1 марта» (art. 339 part 5); payment by the same
    # days (art. 340 part 1) (H). Not for simplified VAT (0 %, no return: UP-100 item 6(b)).
    Rule(
        "profit", "profit", _("Profit tax return and payment"), "quarter", "file_pay", "end", 1,
        20, (VAT,), "Tax Code arts. 338–340", CODE_RU, CODE_2020, quarters=(1, 2, 3),
    ),
    Rule(
        "profit_year", "profit", _("Profit tax: the year's return and payment"), "year",
        "file_pay", "end", 3, 1, (VAT,), "Tax Code arts. 339, 340", CODE_RU, CODE_2020,
    ),
    # Monthly advances «не позднее двадцать третьего числа каждого месяца» when last year's
    # income was over 20 bn so‘m (art. 340 part 2, ZRU-1108 from 01.01.2026; 10 bn before) (H).
    Rule(
        "profit_advance", "profit", _("Profit tax advance"), "month", "pay", "start", 0, 23,
        (VAT,), "Tax Code art. 340", CODE_RU, date(2026, 1, 1), needs="big_income",
    ),
    # Personal income tax withheld: the calculation monthly «не позднее пятнадцатого числа
    # месяца, следующего за отчетным периодом», the year's by 15 February (art. 389 part 1
    # item 2); paid «одновременно … выплатой доходов …, но не позднее сроков представления
    # налоговой отчетности» (art. 390 part 1) (H). The pension contribution goes with it
    # (Regulation 3577, item 6) (H).
    Rule(
        "income_tax", "income_tax", _("Income tax withheld: calculation and payment"), "month",
        "file_pay", "end", 1, 15, ALL_REGIMES, "Tax Code arts. 389, 390", CODE_RU, CODE_2020,
        needs="payroll", note=_("Pay it together with the salaries, by this day at the latest."),
    ),
    # Social tax: monthly return «не позднее пятнадцатого числа…», the year's by 15 February
    # (art. 407 part 4); payment monthly by the same day (art. 407 part 5) (H).
    Rule(
        "social_tax", "social_tax", _("Social tax return and payment"), "month", "file_pay",
        "end", 1, 15, ALL_REGIMES, "Tax Code arts. 406, 407", CODE_RU, CODE_2020, needs="payroll",
    ),
    Rule(
        "payroll_year", "income_tax", _("Income and social tax: the year's returns"), "year",
        "file", "end", 2, 15, ALL_REGIMES, "Tax Code arts. 389, 407", CODE_RU, CODE_2020,
        needs="payroll",
    ),
    # Property tax: the year's estimate (справка) by 20 January (art. 417 part 5); advances by
    # VAT payers «не позднее 10 числа каждого месяца» 1/12, January by 20 January; by
    # turnover-tax payers «не позднее 20 числа третьего месяца каждого квартала» 1/4 (art. 417
    # part 6); the year's return and the rest «не позднее 1 марта» (art. 417 parts 2, 8) (H).
    # The owner pays it, not a tenant (art. 410).
    Rule(
        "property_estimate", "property", _("Property tax: the year's estimate"), "year", "file",
        "start", 0, 20, ALL_REGIMES, "Tax Code art. 417", CODE_RU, CODE_2020, needs="property",
    ),
    Rule(
        "property_advance", "property", _("Property tax advance"), "month", "pay", "start", 0, 10,
        VAT_PAYERS, "Tax Code art. 417", CODE_RU, CODE_2020, needs="property", january_day=20,
    ),
    Rule(
        "property_advance_q", "property", _("Property tax advance"), "quarter", "pay", "end", 0,
        20, (TURNOVER,), "Tax Code art. 417", CODE_RU, CODE_2020, needs="property",
    ),
    Rule(
        "property_year", "property", _("Property tax: the year's return and payment"), "year",
        "file_pay", "end", 3, 1, ALL_REGIMES, "Tax Code art. 417", CODE_RU, CODE_2020,
        needs="property",
    ),
    # Land tax: the return for the year by 20 January (art. 431 part 1); payment by VAT payers
    # 1/12 by the 10th of each month, January by 20 January; by turnover-tax payers 1/4 by the
    # 20th of each quarter's third month (art. 432 part 1) (H). A landlord pays it (art. 425).
    Rule(
        "land_return", "land", _("Land tax return"), "year", "file", "start", 0, 20, ALL_REGIMES,
        "Tax Code art. 431", CODE_RU, CODE_2020, needs="land",
    ),
    Rule(
        "land_advance", "land", _("Land tax payment"), "month", "pay", "start", 0, 10,
        VAT_PAYERS, "Tax Code art. 432", CODE_RU, CODE_2020, needs="land", january_day=20,
    ),
    Rule(
        "land_advance_q", "land", _("Land tax payment"), "quarter", "pay", "end", 0, 20,
        (TURNOVER,), "Tax Code art. 432", CODE_RU, CODE_2020, needs="land",
    ),
)  # fmt: skip

RULES_BY_KEY = {rule.key: rule for rule in RULES}

# Last year's income above which profit tax is paid in monthly advances (art. 340 part 2: «двадцать
# миллиардов сумов» from 01.01.2026, H).
PROFIT_ADVANCE_INCOME = Decimal(20_000_000_000)

# The base calculation value (BHM), so‘m: (from, value, source).
BASE_VALUES: tuple[tuple[date, Decimal, str], ...] = (
    # Decree UP-91 of 02.06.2025 (president.uz, buxgalter.uz; M).
    (date(2025, 8, 1), Decimal(412_000), "Decree UP-91"),
    # Decree UP-115 of 23.06.2026 item 3(b): «базавий ҳисоблаш миқдори — 440 000 сўм» (H).
    (date(2026, 9, 1), Decimal(440_000), "Decree UP-115"),
)

# The turnover-tax threshold: (from, value, unit, source). The year's income over it means VAT
# and profit tax from the day it is reached (art. 462 part 7, counted from 1 January, H).
TURNOVER_THRESHOLDS: tuple[tuple[date, Decimal, str, str], ...] = (
    # Art. 461 part 1 item 1: «не превышает один миллиард сумов» (H).
    (date(2020, 1, 1), Decimal(1_000_000_000), "som", "Tax Code art. 461"),
    # UP-100 item 2: «… 1 июня 2026 года … двенадцатитысячекратный размер базовой расчетной
    # величины» (H).
    (date(2026, 6, 1), Decimal(12_000), "base_values", "Decree UP-100, item 2"),
)

# Pharmacies can't pay turnover tax: art. 461 part 2 item 14 «предприятиям, занимающимся
# торговлей лекарственными средствами, изделиями медицинского назначения …» (ZRU-1104 of
# 25.12.2025, applies from 01.04.2025) (H).
PHARMACY_TURNOVER_BAN = date(2025, 4, 1)
PHARMACY_TURNOVER_LAW = "Tax Code art. 461, part 2, item 14"

SOURCES = (
    {"label": "Tax Code of the Republic of Uzbekistan (lex.uz, Russian)", "url": CODE_RU},
    {"label": "O‘zbekiston Respublikasi Soliq kodeksi (lex.uz)", "url": CODE_UZ},
    {"label": "Decree UP-100 of 26.05.2026", "url": UP_100},
    {"label": "Decree UP-115 of 23.06.2026", "url": UP_115},
)
CHECKED_ON = date(2026, 11, 12)


def base_value(on: date) -> Decimal:
    """The BHM in force on `on`."""
    found = BASE_VALUES[0][1]
    for since, value, _source in BASE_VALUES:
        if since <= on:
            found = value
    return found


def turnover_threshold(on: date) -> tuple[Decimal, str, str]:
    """(amount in so‘m, how it is set, source) of the turnover-tax threshold on `on`."""
    found = TURNOVER_THRESHOLDS[0]
    for row in TURNOVER_THRESHOLDS:
        if row[0] <= on:
            found = row
    _since, value, unit, source = found
    amount = value * base_value(on) if unit == "base_values" else value
    return amount, unit, source


def in_force(rule: Rule, on: date) -> bool:
    return rule.valid_from <= on and (rule.valid_to is None or on < rule.valid_to)
