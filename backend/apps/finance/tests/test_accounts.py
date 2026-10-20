import pytest

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.finance import services
from apps.finance.models import MoneyAccount
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def branch(books):
    return BranchFactory(company=books, name="Chilonzor")


class TestCreateAccount:
    def test_an_account_is_made_and_audited(self, books, owner, branch):
        account = services.create_account(
            books, by=owner, kind="bank", name=" Kapitalbank ", currency="USD", branch=branch
        )

        assert (account.name, account.kind, account.currency, account.branch) == (
            "Kapitalbank",
            "bank",
            "USD",
            branch,
        )
        assert account.balance == 0
        log = AuditLog.objects.get(action="finance.account_created")
        assert (log.actor, log.target_id) == (owner.user, account.pk)

    def test_names_are_unique_whatever_the_case(self, books, owner):
        services.create_account(books, by=owner, kind="bank", name="Kapitalbank")
        with pytest.raises(DomainError, match="already an account"):
            services.create_account(books, by=owner, kind="card", name="KAPITALBANK")
        with pytest.raises(DomainError, match="name"):
            services.create_account(books, by=owner, kind="card", name="   ")

    def test_one_safe_per_branch_and_currency(self, books, owner, branch):
        services.create_account(books, by=owner, kind="safe", name="Safe", branch=branch)
        services.create_account(
            books, by=owner, kind="safe", name="Dollar safe", branch=branch, currency="USD"
        )
        with pytest.raises(DomainError, match="already has a safe"):
            services.create_account(books, by=owner, kind="safe", name="Safe 2", branch=branch)

    def test_employee_and_owner_accounts_need_a_holder(self, books, owner, member):
        with pytest.raises(DomainError, match="holds"):
            services.create_account(books, by=owner, kind="employee", name="Cash")
        worker = member(books)
        services.create_account(books, by=owner, kind="employee", name="Ali", holder=worker)
        with pytest.raises(DomainError, match="already has an account"):
            services.create_account(books, by=owner, kind="employee", name="Ali 2", holder=worker)

    def test_links_and_actor_belong_to_the_company(self, books, owner, other_company):
        with pytest.raises(DomainError, match="same company"):
            services.create_account(
                books, by=owner, kind="safe", name="X", branch=BranchFactory(company=other_company)
            )
        with pytest.raises(DomainError, match="same company"):
            services.create_account(
                books,
                by=owner,
                kind="employee",
                name="X",
                holder=MembershipFactory(company=other_company),
            )
        with pytest.raises(DomainError, match="same company"):
            services.create_account(
                books, by=MembershipFactory(company=other_company), kind="bank", name="X"
            )

    def test_unknown_kinds_and_currencies_are_programming_errors(self, books, owner):
        with pytest.raises(ValueError):
            services.create_account(books, by=owner, kind="piggy", name="X")
        with pytest.raises(ValueError):
            services.create_account(books, by=owner, kind="bank", name="X", currency="EUR")

    def test_the_system_may_make_one(self, books):
        account = services.create_account(books, by=None, kind="cash", name="Till 1")
        assert AuditLog.objects.get(target_id=account.pk).actor is None


class TestAccountForHolder:
    def test_one_account_per_person_kind_and_currency(self, books, member):
        worker = member(books, first_name="Ali", last_name="Valiyev")
        first = services.account_for_holder(books, worker)
        again = services.account_for_holder(books, worker)
        dollars = services.account_for_holder(books, worker, currency="USD")
        own = services.account_for_holder(books, worker, kind="owner")

        assert first == again
        assert len({first.pk, dollars.pk, own.pk}) == 3
        assert (first.kind, first.holder, first.currency) == ("employee", worker, "UZS")
        assert first.name == "Ali Valiyev, cash on hand"
        assert dollars.name == "Ali Valiyev, cash on hand (USD)"
        assert own.name == "Ali Valiyev, own money"
        assert MoneyAccount.objects.filter(holder=worker).count() == 3

    def test_the_account_sits_in_the_persons_home_branch(self, books, member):
        branch = BranchFactory(company=books)
        worker = member(books, home_branch=branch)
        worker.branches.add(branch)

        assert services.account_for_holder(books, worker).branch == branch

    def test_a_taken_name_gets_a_number(self, books, member):
        worker = member(books, first_name="Ali", last_name="Valiyev")
        MoneyAccount.objects.create(company=books, kind="cash", name="Ali Valiyev, cash on hand")

        assert services.account_for_holder(books, worker).name == "Ali Valiyev, cash on hand (2)"

    def test_an_archived_account_is_reopened(self, books, member):
        worker = member(books)
        first = services.account_for_holder(books, worker)
        first.is_active = False
        first.save()

        again = services.account_for_holder(books, worker)

        assert again == first
        assert again.is_active
        assert AuditLog.objects.filter(action="finance.account_reopened").count() == 1

    def test_rules(self, books, member, other_company):
        with pytest.raises(ValueError):
            services.account_for_holder(books, member(books), kind="cash")
        with pytest.raises(DomainError, match="same company"):
            services.account_for_holder(books, MembershipFactory(company=other_company))


class TestAccountForBranch:
    def test_one_safe_per_branch_and_currency(self, books, branch):
        safe = services.account_for_branch(branch)
        again = services.account_for_branch(branch)
        dollar_safe = services.account_for_branch(branch, currency="USD")
        till = services.account_for_branch(branch, kind="cash")

        assert safe == again
        assert len({safe.pk, dollar_safe.pk, till.pk}) == 3
        assert (safe.kind, safe.branch, safe.currency, safe.holder) == ("safe", branch, "UZS", None)
        assert safe.name == "Chilonzor, Safe"
        assert dollar_safe.name == "Chilonzor, Safe (USD)"
        assert services.account_for_branch(branch, kind="cash") == till

    def test_an_archived_safe_is_reopened(self, books, branch):
        safe = services.account_for_branch(branch)
        safe.is_active = False
        safe.save()

        assert services.account_for_branch(branch).is_active

    def test_holder_kinds_are_refused(self, books, branch):
        with pytest.raises(ValueError):
            services.account_for_branch(branch, kind="employee")
        with pytest.raises(ValueError):
            services.account_for_branch(branch, currency="EUR")
