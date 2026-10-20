from django.utils.translation import gettext as _
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.exceptions import DomainError
from apps.members.api import IsCompanyMember, requires
from apps.members.permissions import Perm
from apps.reminders.models import ReminderPolicy
from apps.tasks.models import Weekday


class ReminderPolicySerializer(serializers.ModelSerializer):
    quiet_days = serializers.ListField(
        child=serializers.ChoiceField(Weekday.choices), required=False, help_text="0 = Monday."
    )

    class Meta:
        model = ReminderPolicy
        fields = (
            "id",
            "name",
            "is_default",
            "heads_up_minutes",
            "repeat_every_minutes",
            "max_reminders",
            "escalate_after",
            "quiet_from",
            "quiet_until",
            "quiet_days",
            "snooze_minutes",
            "max_snoozes",
            "replace_previous",
        )
        read_only_fields = ("is_default",)


class ReminderPolicyViewSet(viewsets.ModelViewSet):
    """How hard the bot chases late work. Needs reminders.configure."""

    permission_classes = (IsAuthenticated, IsCompanyMember, requires(Perm.REMINDERS_CONFIGURE))
    serializer_class = ReminderPolicySerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReminderPolicy.objects.none()
        return ReminderPolicy.objects.for_company(self.membership.company)

    def perform_create(self, serializer):
        serializer.save(company=self.membership.company)

    def perform_destroy(self, policy):
        if policy.is_default:
            raise DomainError(_("The company's default policy can't be deleted."))
        policy.delete()
