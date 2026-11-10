"""What matters in a review's facts, ranked: the signals the words are made of.

Each signal is one finding with a stable `key` ("cash:low", "branch:3:margin",
"expense:12"), a `tone` (good or bad), a `weight` for the ranking, the numbers it rests on
(`values`, copied from the facts), what it is about (`subject`: a pharmacy, a group of
expenses, a medicine) and the dashboard page that shows it (`url`). Every point and suggestion
of a review cites one signal by its key; a suggestion that cites no signal of the facts is
dropped (apps.briefings.writing).

A week's profit swings with the days rent and salaries are paid, so the weekly review leaves
profit, losses and the payroll share to the monthly one; both watch revenue, margins, cash,
debts, stock and the team.

    for signal in facts["signals"]:     # the heaviest first
        ...
"""

from decimal import Decimal

GOOD, BAD = "good", "bad"

# How far a figure moves before it counts (percent against the average of the periods before,
# or the period before when there is no average yet; points for a margin or a share).
REVENUE_PCT = Decimal(3)
MARGIN_PTS = {"weekly": Decimal(2), "monthly": Decimal(1)}
BRANCH_MARGIN_PTS = Decimal(2)
PROFIT_PCT = Decimal(10)
EXPENSE_PCT = Decimal(25)
PAYROLL_PTS = Decimal(2)
RECEIPT_PCT = Decimal(5)
LATE_MORE = 3


def _d(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _move(figure: dict) -> Decimal | None:
    """The move of a figure against its average, else against the period before."""
    found = _d(figure.get("vs_average_pct"))
    return found if found is not None else _d(figure.get("change_pct"))


def _signal(key, kind, tone, weight, url, values, subject=None) -> dict:
    return {
        "key": key,
        "kind": kind,
        "tone": tone,
        "weight": float(round(weight, 2)),
        "subject": subject,
        "values": values,
        "url": url,
    }


def _finance(finance: dict, monthly: bool) -> list[dict]:
    found = []
    revenue = finance["revenue"]
    move = _move(revenue)
    if move is not None and abs(move) >= REVENUE_PCT:
        found.append(
            _signal(
                "revenue",
                "revenue",
                GOOD if move > 0 else BAD,
                min(abs(move), 15),
                finance["url"],
                revenue | {"move_pct": str(abs(move))},
            )
        )
    margin = finance["gross_margin"]
    threshold = MARGIN_PTS["monthly" if monthly else "weekly"]
    if margin and (points := _d(margin["change_pts"])) is not None and abs(points) >= threshold:
        found.append(
            _signal(
                "gross_margin",
                "gross_margin",
                GOOD if points > 0 else BAD,
                min(abs(points) * 3, 18),
                finance["url"],
                margin,
            )
        )
    if monthly:
        profit = finance["profit"]
        if _d(profit["value"]) < 0:
            found.append(_signal("profit", "loss", BAD, 25, finance["url"], profit))
        elif (move := _d(profit["vs_average_pct"])) is not None and abs(move) >= PROFIT_PCT:
            found.append(
                _signal(
                    "profit",
                    "profit",
                    GOOD if move > 0 else BAD,
                    min(abs(move) / 2, 14),
                    finance["url"],
                    profit,
                )
            )
    for branch in finance["branches"]:
        name = branch["name"]
        if monthly and _d(branch["profit"]["value"]) < 0:
            found.append(
                _signal(
                    f"branch:{branch['id']}:loss",
                    "branch_loss",
                    BAD,
                    18,
                    branch["url"],
                    branch["profit"],
                    name,
                )
            )
        margin = branch["gross_margin"]
        points = _d(margin["change_pts"]) if margin else None
        if points is not None and abs(points) >= BRANCH_MARGIN_PTS:
            found.append(
                _signal(
                    f"branch:{branch['id']}:margin",
                    "branch_margin",
                    GOOD if points > 0 else BAD,
                    min(abs(points) * 2, 16),
                    branch["url"],
                    margin,
                    name,
                )
            )
    revenue_value = _d(revenue["value"]) or Decimal(0)
    for jump in finance["expense_jumps"]:
        pct = _d(jump["vs_average_pct"])
        grew = _d(jump["change"])
        big_enough = grew >= max(revenue_value / 50, Decimal(500_000))
        if (pct is None or pct >= EXPENSE_PCT) and big_enough:
            found.append(
                _signal(
                    f"expense:{jump['id']}",
                    "expense_jump",
                    BAD,
                    min(float(pct or 100) / 10, 12),
                    jump["url"],
                    {key: jump[key] for key in ("value", "average", "change", "vs_average_pct")},
                    jump["name"],
                )
            )
    payroll = finance["payroll"]["share"]
    points = _d(payroll["vs_average_pts"]) if monthly and payroll else None
    if points is not None and abs(points) >= PAYROLL_PTS:
        found.append(
            _signal(
                "payroll_share",
                "payroll_share",
                BAD if points > 0 else GOOD,
                min(abs(points) * 2, 12),
                finance["url"],
                payroll,
            )
        )
    cash = finance["cash"]
    soon = cash["low_30"]
    if _d(soon["balance"]) < 0:
        found.append(
            _signal(
                "cash:low",
                "cash_below_zero",
                BAD,
                30,
                cash["url"],
                {"now": cash["now"], "date": soon["date"], "balance": soon["balance"]},
            )
        )
    elif cash["below_zero_on"]:
        found.append(
            _signal(
                "cash:runway",
                "cash_runway",
                BAD,
                22,
                cash["url"],
                {
                    "now": cash["now"],
                    "below_zero_on": cash["below_zero_on"],
                    "runway_days": cash["runway_days"],
                },
            )
        )
    elif _d(cash["now"]) > 0:
        found.append(
            _signal(
                "cash:runway",
                "cash_enough",
                GOOD,
                2,
                cash["url"],
                {
                    "now": cash["now"],
                    "horizon_days": cash["horizon_days"],
                    "low_date": cash["low_90"]["date"],
                    "low_balance": cash["low_90"]["balance"],
                },
            )
        )
    for direction, kind, weight in (
        ("receivable", "receivables_overdue", 10),
        ("payable", "payables_overdue", 8),
    ):
        debts = finance["debts"].get(direction)
        if debts and debts["overdue_count"]:
            found.append(
                _signal(
                    f"debts:{direction}",
                    kind,
                    BAD,
                    weight + min(debts["overdue_count"], 4),
                    debts["url"],
                    {
                        "overdue": debts["overdue"],
                        "overdue_count": debts["overdue_count"],
                        "open": debts["open"],
                    },
                )
            )
    return found


def _sales(sales: dict, has_finance: bool) -> list[dict]:
    found = []
    net = sales["net"]
    move = _move(net)
    # With the books on, revenue speaks for sales; without them the till does.
    if not has_finance and move is not None and abs(move) >= REVENUE_PCT:
        found.append(
            _signal(
                "sales:net",
                "revenue",
                GOOD if move > 0 else BAD,
                min(abs(move), 15),
                sales["url"],
                net | {"move_pct": str(abs(move))},
            )
        )
    receipt = sales["average_receipt"]
    move = _move(receipt)
    if move is not None and abs(move) >= RECEIPT_PCT:
        found.append(
            _signal(
                "sales:average_receipt",
                "average_receipt",
                GOOD if move > 0 else BAD,
                min(abs(move), 10),
                sales["url"],
                receipt | {"move_pct": str(abs(move))},
            )
        )
    count = sales["receipts"]
    move = _move(count)
    if move is not None and abs(move) >= RECEIPT_PCT:
        found.append(
            _signal(
                "sales:receipts",
                "receipts",
                GOOD if move > 0 else BAD,
                min(abs(move), 10),
                sales["url"],
                count | {"move_pct": str(abs(move))},
            )
        )
    if _d(sales["cash_difference"]) < 0:
        found.append(
            _signal(
                "sales:cash_difference",
                "cash_difference",
                BAD,
                7,
                sales["url"],
                {"cash_difference": sales["cash_difference"], "shifts": sales["shifts"]},
            )
        )
    return found


def _stock(stock: dict) -> list[dict]:
    found = []
    for row in stock["slow"][:3]:
        found.append(
            _signal(
                f"stock:slow:{row['id']}",
                "slow_stock" if row["sold_lately"] else "dead_stock",
                BAD,
                5 if row["value"] is None else 5 + min(float(Decimal(row["value"])) / 5e6, 5),
                row["url"],
                {
                    key: row[key]
                    for key in ("quantity", "days_of_cover", "value")
                    if row[key] is not None
                }
                | {"velocity_days": stock["velocity_days"]},
                row["name"],
            )
        )
    expiring = stock["expiring"]
    if expiring["count"]:
        found.append(
            _signal(
                "stock:expiring",
                "expiring",
                BAD,
                8,
                expiring["url"],
                {
                    key: expiring[key]
                    for key in ("count", "value", "within_days")
                    if expiring[key] is not None
                },
            )
        )
    return found


def _attendance(attendance: dict) -> list[dict]:
    late = attendance["late"]
    usual = _d(late["average"]) if late["average"] is not None else _d(late["previous"])
    if usual is None:
        return []
    more = late["value"] - usual
    values = late | {"usual": str(usual)}
    if more >= LATE_MORE:
        return [_signal("attendance:late", "late_more", BAD, 6, attendance["url"], values)]
    if more <= -LATE_MORE:
        return [_signal("attendance:late", "late_fewer", GOOD, 4, attendance["url"], values)]
    return []


def _people(people: dict) -> list[dict]:
    if not people["left_count"]:
        return []
    names = [row["name"] for row in people["left"]]
    return [
        _signal(
            "people:left",
            "leavers",
            BAD,
            3,
            people["url"],
            {"count": people["left_count"], "names": names},
        )
    ]


def _insights(rows: list[dict]) -> list[dict]:
    weights = {"critical": 22, "warning": 10}
    return [
        _signal(
            f"insight:{row['id']}",
            "insight",
            BAD,
            weights.get(row["severity"], 4),
            row["url"],
            {"title": row["title"], "suggested_action": row["suggested_action"]},
            row["title"],
        )
        for row in rows
    ]


def of(facts: dict) -> list[dict]:
    """The signals of `facts`, heaviest first (ties by key, so the order never wobbles)."""
    monthly = facts.get("kind") == "monthly"
    found = []
    if "finance" in facts:
        found += _finance(facts["finance"], monthly)
    if "sales" in facts:
        found += _sales(facts["sales"], "finance" in facts)
    if "stock" in facts:
        found += _stock(facts["stock"])
    if "attendance" in facts:
        found += _attendance(facts["attendance"])
    if "people" in facts:
        found += _people(facts["people"])
    if "insights" in facts:
        found += _insights(facts["insights"])
    found.sort(key=lambda signal: (-signal["weight"], signal["key"]))
    return found


def by_key(facts: dict) -> dict[str, dict]:
    return {signal["key"]: signal for signal in facts.get("signals") or []}
