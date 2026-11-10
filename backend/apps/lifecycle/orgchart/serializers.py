"""The shape of `lifecycle/org/` (read only; the dashboard builds both views from it)."""

from rest_framework import serializers

from apps.lifecycle.orgchart.queries import OWNER, RIGHTS, SELF


class OrgRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position = serializers.CharField(allow_null=True, help_text="The job title's name.")

    class Meta:
        ref_name = "LifecycleOrgRef"


class OrgCompanySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "LifecycleOrgCompany"


class OrgDepartmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
    depth = serializers.IntegerField(help_text="1 at the top.")
    head = OrgRefSerializer(allow_null=True)
    headcount = serializers.IntegerField(help_text="People the viewer sees directly in it.")
    total = serializers.IntegerField(help_text="With every department below it.")

    class Meta:
        ref_name = "LifecycleOrgDepartment"


class OrgBranchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()
    manager = OrgRefSerializer(allow_null=True)
    headcount = serializers.IntegerField(help_text="People the branch view puts under it.")

    class Meta:
        ref_name = "LifecycleOrgBranch"


class OrgPositionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    order = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleOrgPosition"


class OrgLeavingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField(help_text="requested or agreed.")
    day = serializers.DateField(allow_null=True, help_text="The agreed last day, else the asked.")

    class Meta:
        ref_name = "LifecycleOrgLeaving"


class OrgChangeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField(help_text="proposed or approved.")
    effective_on = serializers.DateField()
    parts = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "LifecycleOrgChange"


class OrgPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position_id = serializers.IntegerField(allow_null=True)
    department_id = serializers.IntegerField(allow_null=True)
    home_branch_id = serializers.IntegerField(allow_null=True)
    branch_id = serializers.IntegerField(
        allow_null=True, help_text="Where the branch view puts them (their home branch if shown)."
    )
    manager_id = serializers.IntegerField(allow_null=True, help_text="Their nearest head.")
    is_owner = serializers.BooleanField()
    status = serializers.CharField(help_text="approved or suspended.")
    suspended_until = serializers.DateField(allow_null=True)
    on_leave_until = serializers.DateField(allow_null=True)
    leaving = OrgLeavingSerializer(allow_null=True)
    change = OrgChangeSerializer(allow_null=True, help_text="The next job change waiting.")
    may_move = serializers.BooleanField(help_text="The viewer may propose a job change.")
    why_not = serializers.CharField(
        allow_null=True,
        help_text=f"Why not: {RIGHTS} (no hr.manage), {SELF}, {OWNER} (only an owner moves one).",
    )

    class Meta:
        ref_name = "LifecycleOrgPerson"


class OrgVacancySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    position_id = serializers.IntegerField(allow_null=True)
    branch_id = serializers.IntegerField(allow_null=True)
    department_id = serializers.IntegerField(
        allow_null=True, help_text="Where the department view puts it (None: at the top)."
    )
    applicants = serializers.IntegerField(help_text="Applicants still in the running.")
    new = serializers.IntegerField(help_text="Applicants nobody has looked at yet.")

    class Meta:
        ref_name = "LifecycleOrgVacancy"


class OrgCanSerializer(serializers.Serializer):
    move = serializers.BooleanField(help_text="Proposes job changes (hr.manage).")
    decide = serializers.BooleanField(help_text="May approve a move in the same step.")
    hiring = serializers.BooleanField(help_text="Opens vacancies (hr.hiring).")
    structure = serializers.BooleanField(help_text="Edits the departments.")

    class Meta:
        ref_name = "LifecycleOrgCan"


class OrgChartSerializer(serializers.Serializer):
    today = serializers.DateField()
    company = OrgCompanySerializer()
    owners = OrgRefSerializer(many=True)
    departments = OrgDepartmentSerializer(many=True, help_text="Parents before children.")
    branches = OrgBranchSerializer(many=True)
    positions = OrgPositionSerializer(many=True)
    people = OrgPersonSerializer(many=True)
    vacancies = OrgVacancySerializer(many=True)
    can = OrgCanSerializer()

    class Meta:
        ref_name = "LifecycleOrgChart"
