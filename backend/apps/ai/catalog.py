"""Which model each AI feature uses (v0.3 AI contract §2).

    model = catalog.model_for(company, "flows")      # e.g. "claude-haiku-5-5"

Every Claude call takes its model from here, never from a setting directly: the platform
defaults come from settings (AI_MODEL_*), and the owner may choose another offered model per
feature on the dashboard's Models page (AISettings.models). The v0.3 scaffold ships the final
signature with the defaults only; the Models page work fills in the owner's choices, the model
list and the providers.
"""

from django.conf import settings

# Every feature that calls a model, in the Models page's order.
FEATURES: tuple[str, ...] = (
    "chat",
    "task_drafts",
    "briefing",
    "flows",
    "writing",
    "photo_checker",
)


def default_for(feature: str) -> str:
    """The platform's model for `feature` (settings), before any owner choice."""
    defaults = {
        "chat": settings.AI_MODEL_CHAT,
        "task_drafts": settings.AI_MODEL_DRAFTS,
        "briefing": settings.AI_MODEL_CHAT,
        "flows": settings.AI_MODEL_FAST,
        "writing": settings.AI_MODEL_CHAT,
        "photo_checker": settings.AI_MODEL_CHAT,
    }
    if feature not in defaults:
        raise ValueError(f"Unknown AI feature {feature!r}.")
    return defaults[feature]


def model_for(company, feature: str) -> str:
    """The model `feature` uses in `company`."""
    return default_for(feature)
