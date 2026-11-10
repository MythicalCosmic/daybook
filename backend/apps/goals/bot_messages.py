"""What the owner bot says about business goals: plain, short, no emoji."""

from datetime import date
from decimal import Decimal

from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.core.money import format_money
from apps.goals.metrics import MetricSpec


def amount(metric: MetricSpec, value: Decimal | None, currency: str, language: str) -> str:
    """A metric's value as people read it: so‘m, a percent or a count."""
    if value is None:
        return "—"
    if metric.unit == "money":
        return format_money(value, currency, language)
    if metric.unit == "percent":
        text = f"{value.quantize(Decimal('0.1')):f}"
        return f"{text.replace('.', ',') if language != 'en' else text}\u00a0%"
    return f"{int(value)}"


def worse_title(state: str, title: str) -> str:
    if state == "off_track":
        return _("Goal off track: %(title)s") % {"title": title}
    return _("Goal at risk: %(title)s") % {"title": title}


def worse_body(
    metric: MetricSpec,
    *,
    value: Decimal | None,
    forecast: Decimal | None,
    target: Decimal,
    ends_on: date,
    currency: str,
    language: str,
) -> str:
    """Where it stands and where the pace leads, without a placeholder that takes an ending."""
    lines = [
        _("%(metric)s now: %(value)s. Target: %(target)s.")
        % {
            "metric": metric.label,
            "value": amount(metric, value, currency, language),
            "target": amount(metric, target, currency, language),
        }
    ]
    if forecast is not None and metric.kind in ("sum", "rate"):
        lines.append(
            _("At this pace by the end: %(forecast)s.")
            % {"forecast": amount(metric, forecast, currency, language)}
        )
    lines.append(_("Deadline: %(date)s.") % {"date": date_format(ends_on, "j E Y")})
    return "\n".join(lines)
