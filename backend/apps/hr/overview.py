"""The HR overview page (`GET hr/overview/`) and the facts the AI tool and briefs reuse:
headcount and its trend, documents that expire, contracts that end, probations that finish,
birthdays and work anniversaries of the coming week. Branch-scoped throughout."""

from datetime import date, timedelta

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.hr import conf, queries
from apps.hr.models import DocumentKind, EmployeeProfile
from apps.hr.serializers import PersonRefSerializer
from apps.members.queries import person_ref

TREND_MONTHS = 12
LIST_LIMIT = 10
CELEBRATION_DAYS = 7


def build(company, viewer, *, branch_ids: list[int] | None, day: date | None = None) -> dict:
    """Everything the overview shows, as plain data (dates as dates)."""
    day = day or queries.today(company)
    settings = conf.get_settings(company)
    employed = list(
        queries.people(company, branch_ids=branch_ids, statuses=queries.EMPLOYED).select_related(
            "user"
        )
    )
    dates = queries.employment_dates(company, [member.pk for member in employed])
    current = [member for member in employed if member.status in queries.CURRENT]
    expiring = list(
        queries.expiring_documents(
            company, branch_ids=branch_ids, day=day, within=settings.document_warn_days
        )
    )
    checks = queries.compliance(company, branch_ids=branch_ids, day=day)["totals"]
    month_ago = day - timedelta(days=30)
    return {
        "as_of": day,
        "headcount": {
            "current": len(current),
            "active": sum(1 for member in current if member.status == "approved"),
            "suspended": sum(1 for member in current if member.status == "suspended"),
            "joined_30d": sum(
                1 for member in current if dates.get(member.pk) and dates[member.pk][0] > month_ago
            ),
            "left_30d": sum(
                1
                for member in employed
                if dates.get(member.pk) and dates[member.pk][1] and dates[member.pk][1] > month_ago
            ),
        },
        "trend": trend(dates, day),
        "documents": {
            "expired": sum(1 for document in expiring if document.expires_on < day),
            "expiring": sum(1 for document in expiring if document.expires_on >= day),
            "missing": checks[queries.MISSING],
            "unverified": checks[queries.UNVERIFIED],
        },
        "expiring_documents": [
            {
                "id": document.pk,
                "member": document.membership,
                "kind": document.kind,
                "title": document.title,
                "expires_on": document.expires_on,
                "days_left": (document.expires_on - day).days,
            }
            for document in expiring[:LIST_LIMIT]
        ],
        **contract_part(company, branch_ids=branch_ids, day=day, settings=settings),
        "birthdays": birthdays(current, day, CELEBRATION_DAYS),
        "anniversaries": anniversaries(current, dates, day, CELEBRATION_DAYS),
    }


def contract_part(company, *, branch_ids, day: date, settings) -> dict:
    """Contract counts, contracts ending and probations finishing (contracts come next)."""
    return {
        "contracts": {
            "active": 0,
            "drafts": 0,
            "ending": 0,
            "on_probation": 0,
            "without_contract": 0,
        },
        "ending_contracts": [],
        "probation_endings": [],
    }


def trend(dates: dict[int, tuple[date, date | None]], day: date) -> list[dict]:
    """Headcount at the end of each of the last 12 months (today for this one), with the
    people who came and left in it."""
    months = []
    first = day.replace(day=1)
    for _ in range(TREND_MONTHS):
        months.append(first)
        first = (first - timedelta(days=1)).replace(day=1)
    rows = []
    for start in reversed(months):
        end = min(_month_end(start), day)
        rows.append(
            {
                "month": start.strftime("%Y-%m"),
                "headcount": sum(
                    1
                    for hired, left in dates.values()
                    if hired <= end and (left is None or left >= end)
                ),
                "hired": sum(1 for hired, _left in dates.values() if start <= hired <= end),
                "left": sum(1 for _hired, left in dates.values() if left and start <= left <= end),
            }
        )
    return rows


def birthdays(members, day: date, days: int) -> list[dict]:
    """Birthdays from `day` on for `days` days, of people who show theirs."""
    profiles = EmployeeProfile.objects.filter(
        membership__in=members, show_birthday=True, birth_date__isnull=False
    ).select_related("membership__user")
    found = []
    for profile in profiles:
        when = next_date(profile.birth_date, day)
        if (when - day).days < days:
            found.append(
                {"member": profile.membership, "date": when, "days_until": (when - day).days}
            )
    return sorted(found, key=lambda row: (row["date"], row["member"].full_name))


def anniversaries(members, dates, day: date, days: int) -> list[dict]:
    """Work anniversaries (a whole year or more) from `day` on for `days` days."""
    found = []
    for member in members:
        hired = dates.get(member.pk, (None, None))[0]
        if hired is None:
            continue
        when = next_date(hired, day)
        years = when.year - hired.year
        if years >= 1 and (when - day).days < days:
            found.append(
                {"member": member, "date": when, "years": years, "days_until": (when - day).days}
            )
    return sorted(found, key=lambda row: (row["date"], row["member"].full_name))


def next_date(anchor: date, day: date) -> date:
    """The next time (from `day` on) the day and month of `anchor` come round; 29 February is
    kept on 28 February in other years."""
    for year in (day.year, day.year + 1):
        try:
            when = anchor.replace(year=year)
        except ValueError:
            when = date(year, 2, 28)
        if when >= day:
            return when
    return when


def _month_end(start: date) -> date:
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


# Shapes -------------------------------------------------------------------------------


class HeadcountSerializer(serializers.Serializer):
    current = serializers.IntegerField(help_text="Working here now (suspended included).")
    active = serializers.IntegerField()
    suspended = serializers.IntegerField()
    joined_30d = serializers.IntegerField()
    left_30d = serializers.IntegerField()

    class Meta:
        ref_name = "HrHeadcount"


class TrendPointSerializer(serializers.Serializer):
    month = serializers.CharField(help_text="YYYY-MM")
    headcount = serializers.IntegerField()
    hired = serializers.IntegerField()
    left = serializers.IntegerField()

    class Meta:
        ref_name = "HrTrendPoint"


class DocumentCountsSerializer(serializers.Serializer):
    expired = serializers.IntegerField()
    expiring = serializers.IntegerField()
    missing = serializers.IntegerField(help_text="Required documents nobody uploaded.")
    unverified = serializers.IntegerField()

    class Meta:
        ref_name = "HrDocumentCounts"


class ExpiringDocumentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member = serializers.SerializerMethodField()
    kind = serializers.ChoiceField(DocumentKind.choices)
    title = serializers.CharField()
    expires_on = serializers.DateField()
    days_left = serializers.IntegerField(help_text="Negative once expired.")

    class Meta:
        ref_name = "HrExpiringDocument"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row) -> dict:
        return person_ref(row["member"])


class ContractCountsSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    drafts = serializers.IntegerField()
    ending = serializers.IntegerField(help_text="Active, ending within the warning days.")
    on_probation = serializers.IntegerField()
    without_contract = serializers.IntegerField(help_text="Current people with no active one.")

    class Meta:
        ref_name = "HrContractCounts"


class ContractDateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member = serializers.SerializerMethodField()
    number = serializers.CharField()
    date = serializers.DateField()
    days_left = serializers.IntegerField(help_text="Negative once past.")

    class Meta:
        ref_name = "HrContractDate"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row) -> dict:
        return person_ref(row["member"])


class BirthdaySerializer(serializers.Serializer):
    member = serializers.SerializerMethodField()
    date = serializers.DateField()
    days_until = serializers.IntegerField()

    class Meta:
        ref_name = "HrBirthday"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row) -> dict:
        return person_ref(row["member"])


class AnniversarySerializer(BirthdaySerializer):
    years = serializers.IntegerField()

    class Meta:
        ref_name = "HrAnniversary"


class OverviewSerializer(serializers.Serializer):
    as_of = serializers.DateField()
    headcount = HeadcountSerializer()
    trend = TrendPointSerializer(many=True)
    documents = DocumentCountsSerializer()
    expiring_documents = ExpiringDocumentSerializer(many=True)
    contracts = ContractCountsSerializer()
    ending_contracts = ContractDateSerializer(many=True)
    probation_endings = ContractDateSerializer(many=True)
    birthdays = BirthdaySerializer(many=True)
    anniversaries = AnniversarySerializer(many=True)

    class Meta:
        ref_name = "HrOverview"
