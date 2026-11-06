"""An owner's own instructions to an agent ("Fridge problems are always urgent", "Mention the
fridge checks first"), kept on its AgentState and added after the agent's own system prompt each
time it asks Claude. They come from someone who may set up AI (ai.configure), so Claude follows
them, but after the agent's rules: the rules, the answer's format and what it may share stay
first. Shown on the agent's page next to the prompts it adds to (Agent.prompts)."""

from apps.ai.models import AgentState

MAX_LENGTH = 1000
INTRO = (
    "The company's owner added these instructions for this work. Follow them where they fit the "
    "rules above; the rules above, what you may share and the answer's format always come first."
)


def of(company, key: str) -> str:
    """The company's instructions for agent `key`, "" when it has none."""
    found = (
        AgentState.objects.filter(company=company, key=key)
        .values_list("instructions", flat=True)
        .first()
    )
    return (found or "").strip()


def system_for(company, key: str, base: str) -> str:
    """`base` (an agent's system prompt) with the company's instructions for it after it."""
    text = of(company, key)
    if not text:
        return base
    return f"{base}\n\n{INTRO}\n<company_instructions>\n{text}\n</company_instructions>"
