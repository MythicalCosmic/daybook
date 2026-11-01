"""Demo data of the AI features: Demo Dorixona has AI on, as its owner's consent leaves it,
with the default agents switched on."""

from apps.ai import services


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    services.enable_ai(company, by=people["owner"])
