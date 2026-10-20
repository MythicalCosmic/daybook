from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import UnfoldAdminCheckboxSelectMultipleWidget

from apps.groups.models import GroupEvent, TelegramGroup
from apps.members.models import Position


class TelegramGroupForm(forms.ModelForm):
    events = forms.MultipleChoiceField(
        choices=GroupEvent.choices,
        required=False,
        widget=UnfoldAdminCheckboxSelectMultipleWidget,
    )

    class Meta:
        model = TelegramGroup
        fields = ("company", "title", "chat_id", "events", "positions", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "positions" in self.fields and self.instance.company_id:
            self.fields["positions"].queryset = Position.objects.for_company(
                self.instance.company_id
            )

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")
        company_id = company.pk if company else self.instance.company_id
        positions = cleaned.get("positions") or []
        # Tenant guard: another company's positions must never filter this group.
        if any(position.company_id != company_id for position in positions):
            self.add_error("positions", _("Pick positions from this group's company."))
        return cleaned
