"""What happens to a company, for other apps to react to. Every signal is sent on commit.

    company_created  company, by   companies.services.setup_company (from create_company and
                                   from CompanyAdmin.save_model); modules run their
                                   `defaults.ensure(company)` from it

`by` is the acting Membership, or None (Django admin, management commands).
"""

from django.dispatch import Signal

company_created = Signal()
