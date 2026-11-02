"""The AI models, providers and features (v0.3 AI contract §1), and the model each feature uses.

    model = catalog.model_for(company, "flows")      # e.g. "claude-haiku-5-5"

Every Claude call takes its model from here, never from a setting directly: the platform's
default per feature comes from settings (AI_MODEL_*), and an owner may choose another offered
model per feature on the dashboard's Models page (`AISettings.models`). A choice that is unknown,
or no longer offered, falls back to the default. Prices live in `apps.ai.pricing`.

Only Anthropic's models are offered ("for now anthropic is enough, haiku or sonnet"); the other
providers are listed as coming soon, have no models, and nothing calls them.
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class Model:
    id: str
    provider: str
    name: str
    tier: str  # "fast" | "smart"
    description: Promise
    vision: bool = True


@dataclass(frozen=True)
class Provider:
    key: str
    name: str | Promise
    description: Promise
    website: str
    live: bool  # False: coming soon (no models, never called)


@dataclass(frozen=True)
class Feature:
    key: str
    name: Promise
    description: Promise
    # The setting with the platform's default model.
    setting: str
    needs_vision: bool = False


# Offered models, in the Models page's order.
MODELS: tuple[Model, ...] = (
    Model(
        id="claude-haiku-5-5",
        provider=ANTHROPIC,
        name="Claude Haiku 5.5",
        tier="fast",
        description=_("Fast and inexpensive: short messages, checks, flows"),
    ),
    Model(
        id="claude-sonnet-5-5",
        provider=ANTHROPIC,
        name="Claude Sonnet 5.5",
        tier="smart",
        description=_("Careful: answers over your data, reports, writing"),
    ),
)

PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key=ANTHROPIC,
        name="Anthropic",
        description=_("Claude models, called from our server with the platform's key"),
        website="https://www.anthropic.com/claude",
        live=True,
    ),
    Provider(
        key="nvidia",
        name="NVIDIA NIM",
        description=_(
            "Open models — Nemotron, Llama, Mistral and more — on NVIDIA's cloud or your own "
            "GPU server"
        ),
        website="https://build.nvidia.com",
        live=False,
    ),
    Provider(
        key="openai_compatible",
        name=_("Your own server"),
        description=_("Any OpenAI-compatible endpoint: vLLM, Ollama, LM Studio"),
        website="",
        live=False,
    ),
)

_FEATURES: tuple[Feature, ...] = (
    Feature(
        "chat",
        _("Ask AI"),
        _("Answers questions about the company's work from its own data"),
        "AI_MODEL_CHAT",
    ),
    Feature(
        "task_drafts",
        _("Voice tasks"),
        _("Turns voice notes and typed instructions into tasks"),
        "AI_MODEL_DRAFTS",
    ),
    Feature(
        "briefing",
        _("Briefing"),
        _("The day or the week in a few lines, and the managers' morning plan"),
        "AI_MODEL_CHAT",
    ),
    Feature(
        "flows",
        _("Flows"),
        _("The AI steps of flows: short messages, decisions, summaries"),
        "AI_MODEL_FAST",
    ),
    Feature(
        "writing",
        _("Writing help"),
        _("Improves, shortens and translates announcements and task descriptions"),
        "AI_MODEL_CHAT",
    ),
    Feature(
        "photo_checker",
        _("Photo checker"),
        _("Reads proof photos: fridge thermometers, expiry dates"),
        "AI_MODEL_CHAT",
        needs_vision=True,
    ),
)
_BY_KEY = {feature.key: feature for feature in _FEATURES}

# Every feature that calls a model, in the Models page's order.
FEATURES: tuple[str, ...] = tuple(_BY_KEY)

# What each `AIUsage.feature` value is spent on, by catalog feature (the Models page's usage).
# The morning plan is the managers' briefing; values starting with "flow" are flow steps.
USAGE_FEATURES = {
    "chat": "chat",
    "task_drafts": "task_drafts",
    "briefing": "briefing",
    "morning_plan": "briefing",
    "insight": "briefing",
    "flows": "flows",
    "writing": "writing",
    "photo_checker": "photo_checker",
}
OTHER = "other"


def get_feature(key: str) -> Feature:
    if key not in _BY_KEY:
        raise ValueError(f"Unknown AI feature {key!r}.")
    return _BY_KEY[key]


def get_model(model_id: str | None) -> Model | None:
    """The offered model `model_id`, or None."""
    return next((model for model in MODELS if model.id == model_id), None)


def offered(model_id: str | None) -> bool:
    return get_model(model_id) is not None


def choices_for(feature: str) -> list[str]:
    """The offered models `feature` may use (a feature that reads photos needs vision)."""
    needs_vision = get_feature(feature).needs_vision
    return [model.id for model in MODELS if model.vision or not needs_vision]


def default_for(feature: str) -> str:
    """The platform's model for `feature` (settings), before any owner choice."""
    return getattr(settings, get_feature(feature).setting)


def model_for(company, feature: str) -> str:
    """The model `feature` uses in `company`: the owner's choice when it is still offered (and
    fits the feature), else the platform's default."""
    if company is None:
        return default_for(feature)
    from apps.ai import conf

    return pick(feature, conf.get_settings(company).models)


def pick(feature: str, chosen: dict | None) -> str:
    """The model of `feature` given the owner's choices (`AISettings.models`)."""
    model_id = (chosen or {}).get(feature)
    return model_id if model_id in choices_for(feature) else default_for(feature)


def usage_feature(value: str) -> str:
    """The catalog feature an `AIUsage.feature` value counts towards ("other" when none)."""
    if value in USAGE_FEATURES:
        return USAGE_FEATURES[value]
    return "flows" if value.startswith("flow") else OTHER


def display_name(model_id: str) -> str:
    """A model's name for people: the catalog's, else built from the id ("claude-opus-5-5" →
    "Claude Opus 5.5": a fallback may have answered with a model the catalog doesn't offer)."""
    if model := get_model(model_id):
        return model.name
    parts = model_id.split("-")
    if len(parts) < 2 or parts[0] != "claude":
        return model_id
    words = [part for part in parts if not part.isdigit()]
    version = ".".join(part for part in parts if part.isdigit())
    return " ".join([*(word.capitalize() for word in words), version]).strip()
