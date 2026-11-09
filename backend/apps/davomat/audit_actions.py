"""Audit action codes and labels of Davomat (`apps.audit.registry.register`). Passwords and the
bot token never reach an audit row: only that they changed."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class DavomatAction(models.TextChoices):
    SETUP_DONE = "davomat.setup_done", _("Set up the organization")
    SETTINGS_CHANGED = "davomat.settings_changed", _("Changed the Davomat settings")
    PASSWORD_LOGIN = "davomat.password_login", _("Signed in with a password")
    PASSWORD_LOCKED = "davomat.password_locked", _("Sign-in locked after wrong passwords")
    PASSWORD_CHANGED = "davomat.password_changed", _("Changed their password")
    PASSWORD_SET = "davomat.password_set", _("Set a user's password")
    USER_CREATED = "davomat.user_created", _("Added a user")
    USER_CHANGED = "davomat.user_changed", _("Changed a user")
    USER_DEACTIVATED = "davomat.user_deactivated", _("Switched a user off")
    USER_ACTIVATED = "davomat.user_activated", _("Switched a user back on")
    EMPLOYEE_CREATED = "davomat.employee_created", _("Added an employee")
    EMPLOYEE_CHANGED = "davomat.employee_changed", _("Changed an employee")
    EMPLOYEE_PHOTO = "davomat.employee_photo", _("Changed an employee's photo")
    EMPLOYEE_RETURNED = "davomat.employee_returned", _("Took an employee back")
    EMPLOYEE_AUTO_CREATED = "davomat.employee_auto_created", _("A terminal added an employee")
    EMPLOYEES_IMPORTED = "davomat.employees_imported", _("Imported employees")
    TELEGRAM_CONNECTED = "davomat.telegram_connected", _("Connected the Telegram bot")
    TELEGRAM_REMOVED = "davomat.telegram_removed", _("Disconnected the Telegram bot")
    TELEGRAM_LINK_MADE = "davomat.telegram_link_made", _("Made a Telegram link")
    TELEGRAM_LINKED = "davomat.telegram_linked", _("Linked a Telegram account")
    TELEGRAM_UNLINKED = "davomat.telegram_unlinked", _("Unlinked a Telegram account")
