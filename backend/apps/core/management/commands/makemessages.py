"""makemessages that also collects `_l("...")`.

Modules that need a plain and a lazy gettext side by side import `gettext_lazy as _l`
(attendance's reports, T-13 and exports, tasks' feeds), and xgettext only knows Django's own
names: without this their texts never reached the .po files and stayed English.
"""

from django.core.management.commands import makemessages


class Command(makemessages.Command):
    xgettext_options = [*makemessages.Command.xgettext_options, "--keyword=_l"]
