"""Default rows of the AI features for a company."""


def ensure(company) -> None:
    """Create the missing default rows. Idempotent: it runs from `manage.py
    ensure_company_defaults` after every deploy and when a module an agent works for is
    switched on (HR). Where AI is on, an agent that is on by default and was never set up in
    the company (no state row: one added in a later release, or one whose module just came
    on) is switched on, as the owner's consent would have done."""
    from apps.ai import conf, services

    if conf.ai_on(company):
        services.switch_on_default_agents(company, new_only=True)
