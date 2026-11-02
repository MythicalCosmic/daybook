"""What the bots say about the people lifecycle. Call under the reader's language
(`inbox.notify` renders each title and body that way)."""

from django.utils.translation import gettext as _

from apps.lifecycle.models import DisciplinaryRecord


def record_title(record: DisciplinaryRecord) -> str:
    """The kind of record, as the title: "Written warning"."""
    return str(record.get_kind_display())


def record_body(record: DisciplinaryRecord) -> str:
    # Translators: %(category)s is what it is about, e.g. "Storage conditions breached".
    return _("About: %(category)s. Read it in the app; you can write your explanation there.") % {
        "category": record.get_category_display()
    }


def explanation_title(record: DisciplinaryRecord) -> str:
    # Translators: %(name)s is a person's name; it stands alone after the colon.
    return _("Explanation from: %(name)s") % {"name": record.membership}


def explanation_body(record: DisciplinaryRecord) -> str:
    return f"{record.get_kind_display()} · {record.issued_on:%d.%m.%Y}"
