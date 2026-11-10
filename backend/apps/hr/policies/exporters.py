"""The signatures export (`hr.policy_signatures`, Excel or CSV through apps.exports): who signed
the current version of each policy, who is still to sign and who is late, in the requester's
branch scope. `policy` narrows it to one policy, `state` to one standing."""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from rest_framework import serializers

from apps.hr.policies import queries
from apps.members import scope


class Params(serializers.Serializer):
    policy = serializers.IntegerField(required=False, allow_null=True)
    state = serializers.ChoiceField(choices=queries.STATES, required=False, allow_blank=True)


COLUMNS = [
    ("policy", _l("Policy")),
    ("version", _l("Version"), "number"),
    ("person", _l("Person")),
    ("position", _l("Position")),
    ("branch", _l("Branch")),
    ("status", _l("Status")),
    ("asked_at", _l("Asked"), "datetime"),
    ("due_on", _l("Sign by"), "date"),
    ("signed_at", _l("Signed"), "datetime"),
    ("signed_version", _l("Version signed"), "number"),
    ("reminded_at", _l("Last reminder"), "datetime"),
]


def rows(member, params: dict):
    branch_ids = scope.branch_ids(member)
    day = queries.today(member.company)
    labels = {
        queries.SIGNED: _("Signed"),
        queries.WAITING: _("Waiting"),
        queries.LATE: _("Late"),
    }
    found = (
        queries.policies(member.company, branch_ids=branch_ids)
        .filter(is_active=True, requires_ack=True, ack_version__isnull=False)
        .select_related("ack_version")
        .prefetch_related("positions", "branches")
        .order_by("title", "pk")
    )
    if params.get("policy"):
        found = found.filter(pk=params["policy"])
    wanted = params.get("state") or None
    for policy in found:
        for row in queries.grid(policy, branch_ids=branch_ids):
            standing = queries.state(row, day)
            if wanted and standing != wanted:
                continue
            person = row.membership
            yield {
                "policy": policy.title,
                "version": policy.ack_version.number,
                "person": str(person),
                "position": person.position.name if person.position else "",
                "branch": person.home_branch.name if person.home_branch else "",
                "status": str(labels[standing]),
                "asked_at": row.asked_at,
                "due_on": row.due_on,
                "signed_at": row.acknowledged_at,
                "signed_version": row.signed_version.number if row.signed_version else None,
                "reminded_at": row.reminded_at,
            }
