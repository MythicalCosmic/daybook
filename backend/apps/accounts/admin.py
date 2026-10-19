from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from apps.accounts.models import User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        (_("Telegram"), {"fields": ("telegram_id", "telegram_username", "language")}),
    )
    list_display = (
        "username",
        "first_name",
        "last_name",
        "telegram_id",
        "telegram_username",
        "is_staff",
    )
    search_fields = ("username", "first_name", "last_name", "telegram_username", "telegram_id")


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
