from django import forms
from unfold.widgets import UnfoldAdminCheckboxSelectMultipleWidget

from apps.members.models import AccessRole
from apps.members.permissions import Perm


class AccessRoleForm(forms.ModelForm):
    permissions = forms.MultipleChoiceField(
        choices=Perm.choices,
        required=False,
        widget=UnfoldAdminCheckboxSelectMultipleWidget,
    )

    class Meta:
        model = AccessRole
        fields = ("company", "name", "permissions", "is_owner", "is_default")
