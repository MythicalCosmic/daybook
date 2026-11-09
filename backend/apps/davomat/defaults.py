"""Default rows of Davomat for a company: none. The settings row is made on first read
(`conf.get_settings`), the organization's roles at setup (`services.setup_organization`)."""


def ensure(company) -> None:
    """Idempotent, like every app's `ensure`; Davomat has no default rows."""
    return None
