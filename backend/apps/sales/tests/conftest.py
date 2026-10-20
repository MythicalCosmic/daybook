import pytest

from apps.sales.tests.factories import make_shop


@pytest.fixture
def shop(db):
    """A company with sales on: Chilonzor and Yunusobod, a till each, an owner, a manager who
    sees every branch, and a cashier per branch."""
    return make_shop()
