"""The one module that talks to Anthropic (docs/PLAN-OWNER.md §8.1 rule 6, §8.2).

    result = client.structured(
        "task_drafts", company=company, membership=member,
        model=settings.AI_MODEL_DRAFTS, schema=TaskDraftSet, effort="low",
        system=SYSTEM, user=[{"type": "text", "text": "..."}],
    )

Request rules (the `claude-api` skill, Python SDK anthropic 1.11): no `temperature`/`top_p`/
`top_k` (the 1.x SDK has none), thinking stays adaptive (omitted: it can't be switched off on
Opus 5.5), `output_config.effort` always set, structured output through
`output_config.format` with the schema from `anthropic.transform_schema`, and on Opus, Sonnet
and Fable the server-side refusal fallback (`fallbacks="default"`, beta
`server-side-fallback-2026-07-01`); Haiku has none, so its calls never send it. `stop_reason`
is checked before the content is read; every response (refusals included) becomes an AIUsage
row priced by the models that answered (`usage.iterations` when a fallback ran), and one log
line carries the request id, never the prompt or the answer. Failures (429, 5xx, timeouts,
connection) feed the circuit breaker in `apps.ai.availability`.

Tests replace `get_client()` with `apps.ai.fakes.FakeAnthropic` (fixture `fake_claude`).
"""

import functools
import logging
import time
from dataclasses import dataclass

import anthropic
from django.conf import settings
from pydantic import BaseModel, ValidationError

from apps.ai import availability, pricing

logger = logging.getLogger("apps.ai")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models with a server-side refusal fallback (Haiku has none).
FALLBACK_LINES = ("claude-opus-", "claude-sonnet-", "claude-fable-")
# Non-streaming structured calls stay at or below this, so they finish within the SDK's
# HTTP timeout (§8.2).
MAX_STRUCTURED_TOKENS = 16_000
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class ClaudeError(Exception):
    """A call that gave nothing usable; `code` says why. Callers take their no-AI path."""

    code = "error"


class Unavailable(ClaudeError):
    code = "unavailable"  # 429, 5xx, timeout, connection, or no key


class Refused(ClaudeError):
    code = "refused"


class Truncated(ClaudeError):
    code = "max_tokens"


class InvalidOutput(ClaudeError):
    code = "invalid_output"


@dataclass(frozen=True)
class Call:
    """What one call produced, besides its parsed result."""

    model: str
    request_id: str
    stop_reason: str
    cost_micro_usd: int
    latency_ms: int


@functools.cache
def _client_for(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=120.0)


def get_client():
    """The SDK client (tests swap in a fake). Without a key there is nothing to call."""
    if not settings.ANTHROPIC_API_KEY:
        raise Unavailable("ANTHROPIC_API_KEY is not set.")
    return _client_for(settings.ANTHROPIC_API_KEY)


def uses_fallbacks(model: str) -> bool:
    return model.startswith(FALLBACK_LINES)


def structured[M: BaseModel](
    feature: str,
    *,
    company,
    membership=None,
    model: str,
    schema: type[M],
    system: str,
    user: str | list[dict],
    effort: str = "low",
    max_tokens: int = MAX_STRUCTURED_TOKENS,
) -> tuple[M, Call]:
    """One structured call: `schema` filled in by `model`, plus what the call cost."""
    if effort not in EFFORTS:
        raise ValueError(f"Unknown effort {effort!r}.")
    request = {
        "model": model,
        "max_tokens": min(max_tokens, MAX_STRUCTURED_TOKENS),
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)},
        },
    }
    if uses_fallbacks(model):
        request |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    response, call = _send(feature, company, membership, request)
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise InvalidOutput("No text block in the answer.")
    try:
        return schema.model_validate_json(text), call
    except ValidationError as exc:
        raise InvalidOutput(str(exc)[:200]) from exc


def converse(
    feature: str,
    *,
    company,
    membership=None,
    model: str,
    system: list[dict] | str,
    messages: list[dict],
    tools: list[dict],
    tool_choice: dict | None = None,
    effort: str = "medium",
    max_tokens: int = MAX_STRUCTURED_TOKENS,
):
    """One round of a tool loop (Ask AI): the response, priced and checked (refusal and
    max_tokens raise). `tool_choice` is only ever "auto" (left out) or {"type": "none"}: forced
    tool use is refused by Opus 5.5 and Sonnet 5.5."""
    if effort not in EFFORTS:
        raise ValueError(f"Unknown effort {effort!r}.")
    if tool_choice is not None and tool_choice.get("type") not in ("auto", "none"):
        raise ValueError("Forced tool use is not accepted by the current models.")
    request = {
        "model": model,
        "max_tokens": min(max_tokens, MAX_STRUCTURED_TOKENS),
        "system": system,
        "messages": messages,
        "tools": tools,
        "output_config": {"effort": effort},
    }
    if tool_choice is not None:
        request["tool_choice"] = tool_choice
    if uses_fallbacks(model):
        request |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    response, _call = _send(feature, company, membership, request)
    return response


def _send(feature: str, company, membership, request: dict):
    started = time.monotonic()
    try:
        response = get_client().beta.messages.create(**request)
    except anthropic.APIStatusError as exc:
        if exc.status_code == 429 or exc.status_code >= 500:
            availability.record_failure()
        _log_failure(feature, company, request["model"], exc, started)
        raise Unavailable(f"Anthropic answered {exc.status_code}.") from exc
    except anthropic.APIConnectionError as exc:  # timeouts included
        availability.record_failure()
        _log_failure(feature, company, request["model"], exc, started)
        raise Unavailable("Anthropic could not be reached.") from exc
    latency_ms = int((time.monotonic() - started) * 1000)
    call = _record(feature, company, membership, request["model"], response, latency_ms)
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        raise Refused(f"Refused ({category or 'no category'}).")
    if response.stop_reason == "max_tokens":
        raise Truncated("The answer hit max_tokens.")
    return response, call


def _record(feature: str, company, membership, requested: str, response, latency_ms: int) -> Call:
    """The AIUsage row and the log line of one response; the month's spend goes up."""
    from apps.ai.models import AIUsage

    usage = response.usage
    served = response.model or requested
    attempts = [entry for entry in (usage.iterations or []) if hasattr(entry, "input_tokens")]
    if attempts:  # a fallback ran: each attempt at its own model's price
        cost = sum(
            pricing.cost_micro_usd(
                getattr(entry, "model", None) or requested,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                cache_read_tokens=entry.cache_read_input_tokens or 0,
                cache_write_tokens=entry.cache_creation_input_tokens or 0,
            )
            for entry in attempts
        )
        input_tokens = sum(entry.input_tokens for entry in attempts)
        output_tokens = sum(entry.output_tokens for entry in attempts)
        cache_read = sum(entry.cache_read_input_tokens or 0 for entry in attempts)
        cache_write = sum(entry.cache_creation_input_tokens or 0 for entry in attempts)
    else:
        input_tokens, output_tokens = usage.input_tokens, usage.output_tokens
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        cost = pricing.cost_micro_usd(
            served,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
    request_id = getattr(response, "_request_id", None) or ""
    AIUsage.objects.create(
        company=company,
        feature=feature,
        membership=membership,
        model=served,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_micro_usd=cost,
        request_id=request_id[:64],
        latency_ms=latency_ms,
        stop_reason=response.stop_reason or "",
    )
    availability.add_spend(company, cost)
    logger.info(
        "claude call company=%s feature=%s requested=%s served=%s request_id=%s in=%s out=%s "
        "cache_read=%s cache_write=%s cost_micro_usd=%s latency_ms=%s stop=%s",
        company.pk,
        feature,
        requested,
        served,
        request_id,
        input_tokens,
        output_tokens,
        cache_read,
        cache_write,
        cost,
        latency_ms,
        response.stop_reason,
    )
    return Call(served, request_id, response.stop_reason or "", cost, latency_ms)


def _log_failure(feature: str, company, model: str, exc: Exception, started: float) -> None:
    logger.warning(
        "claude call failed company=%s feature=%s model=%s error=%s request_id=%s latency_ms=%s",
        company.pk,
        feature,
        model,
        type(exc).__name__,
        getattr(exc, "request_id", None) or "",
        int((time.monotonic() - started) * 1000),
    )
