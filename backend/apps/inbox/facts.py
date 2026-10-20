"""What the inbox contributes to the console's fact registries."""

from apps.companies.models import Company
from apps.console import registry
from apps.console.contracts import InboxCompanyFacts
from apps.console.ranges import Range
from apps.members.models import Membership


def company_facts(company: Company, range: Range, member: Membership) -> InboxCompanyFacts:
    """`waiting`: the items in the caller's Needs you queue in `company` right now."""
    return {"waiting": registry.queue_total(member)}
