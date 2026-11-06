"""The storage preset (PLAN-OWNER §14.10, §14.4 row 29): one dialog sets up a branch's
temperature and humidity journal and its hygiene routines, as shared routines ("one of us
does it": the first person to finish closes the others' copies).

For each reading time (the company's `TasksSettings.storage_times` unless the dialog picks
others): one readings routine per fridge (the fridge range, critical) and one for the room (its
temperature range and the humidity maximum), every range copied from `TasksSettings` into the
routine, where it stays editable. Then daily wet cleaning, weekly disinfection and, at a
pharmacy branch, the daily check that the dispensing camera records and keeps 30 days. The
monthly sanitary day is a company calendar event, not a routine (routines repeat by weekday).

Running it again adds only what the branch doesn't have yet (the same title and time), so a
second fridge is added by running it with `fridges=2`.
"""

from dataclasses import dataclass, field
from datetime import time

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.scope import branch_ids
from apps.tasks import conf, services
from apps.tasks.audit_actions import TasksAction
from apps.tasks.models import Proof, TaskTemplate, Weekday
from apps.tasks.readings import plain

MAX_FRIDGES = 5
EVERY_DAY = list(Weekday.values)
DISINFECTION_DAY = Weekday.MONDAY
CELSIUS = "°C"


@dataclass
class PresetResult:
    created: list[TaskTemplate] = field(default_factory=list)
    # Titles the branch already had at that time, so they were left as they are.
    existing: list[str] = field(default_factory=list)


def default_positions(branch: Branch) -> list[Position]:
    """Every position someone working at `branch` (their home branch) holds."""
    held = Membership.objects.filter(
        company_id=branch.company_id,
        home_branch=branch,
        status=Membership.Status.APPROVED,
        position__isnull=False,
    ).values("position_id")
    return list(Position.objects.for_company(branch.company_id).filter(pk__in=held))


def is_pharmacy(branch: Branch) -> bool:
    """The retail rules (the dispensing camera check) apply at pharmacy branches; until branches
    carry their kind (`Branch.kind`, §14.21) every branch is one, the documented default."""
    return getattr(branch, "kind", "pharmacy") == "pharmacy"


def plans(branch: Branch, *, fridges: int, times: list[time], settings) -> list[dict]:
    """What the preset makes at `branch`, in the company's language, as `create_template`
    fields (without the people)."""
    fridge = {"min": plain(settings.storage_fridge_min), "max": plain(settings.storage_fridge_max)}
    room = {"min": plain(settings.storage_room_min), "max": plain(settings.storage_room_max)}
    humidity = plain(settings.storage_humidity_max)
    made = []
    with translation.override(branch.company.default_language):
        for moment in times:
            clock = moment.strftime("%H:%M")
            for number in range(1, fridges + 1):
                made.append(
                    {
                        "title": _("Fridge %(number)d: temperature, %(time)s")
                        % {"number": number, "time": clock},
                        "description": _(
                            "Read the thermometer inside the fridge and type the number. Out "
                            "of range: move the medicines to a fridge that keeps the range, "
                            "write what you did, and take the reading again."
                        ),
                        "due_time": moment,
                        "weekdays": EVERY_DAY,
                        "proof": Proof.READINGS,
                        "readings": [
                            {
                                "key": "t",
                                "label": _("Fridge %(number)d temperature") % {"number": number},
                                "unit": CELSIUS,
                                **fridge,
                                "critical": True,
                            }
                        ],
                    }
                )
            made.append(
                {
                    "title": _("Room: temperature and humidity, %(time)s") % {"time": clock},
                    "description": _(
                        "Read the thermometer and the hygrometer in the storage room and type "
                        "both numbers."
                    ),
                    "due_time": moment,
                    "weekdays": EVERY_DAY,
                    "proof": Proof.READINGS,
                    "readings": [
                        {
                            "key": "t",
                            "label": _("Room temperature"),
                            "unit": CELSIUS,
                            **room,
                            "critical": False,
                        },
                        {
                            "key": "h",
                            "label": _("Humidity"),
                            "unit": "%",
                            "min": None,
                            "max": humidity,
                            "critical": False,
                        },
                    ],
                }
            )
        first, last = times[0], times[-1]
        made.append(
            {
                "title": _("Wet cleaning"),
                "description": _("Floors, counters and shelves, with a disinfectant."),
                "due_time": last,
                "weekdays": EVERY_DAY,
                "proof": Proof.NONE,
            }
        )
        made.append(
            {
                "title": _("Weekly disinfection"),
                "description": _(
                    "Fridges, shelves, door handles and the counter, with a disinfectant."
                ),
                "due_time": last,
                "weekdays": [DISINFECTION_DAY],
                "proof": Proof.NONE,
            }
        )
        if is_pharmacy(branch):
            made.append(
                {
                    "title": _("Dispensing camera: records and keeps 30 days"),
                    "description": _(
                        "Check that the camera over the counter is recording and that the last "
                        "30 days of video are kept."
                    ),
                    "due_time": first,
                    "weekdays": EVERY_DAY,
                    "proof": Proof.NONE,
                }
            )
    return made


@transaction.atomic
def apply_storage_preset(
    branch: Branch,
    *,
    by: Membership,
    fridges: int = 1,
    positions=(),
    times: list[time] | None = None,
) -> PresetResult:
    """Make the storage routines at `branch` (see the module docstring) for `positions`
    (default: every position at the branch), from the company's `TasksSettings` ranges and
    times (or `times`). Needs tasks.templates and the branch in the caller's scope; each
    routine is audited as created, and the preset once."""
    if not by.has_perm(Perm.TASKS_TEMPLATES):
        raise PermissionDenied(_("You can't change routines."))
    if branch.company_id != by.company_id:
        raise DomainError(_("That isn't part of your company."))
    scope = branch_ids(by)
    if scope is not None and branch.pk not in scope:
        raise PermissionDenied(_("This routine belongs to a branch you don't manage."))
    fridges = int(fridges)
    if not 0 <= fridges <= MAX_FRIDGES:
        raise DomainError(_("Pick 0 to %(max)d fridges.") % {"max": MAX_FRIDGES})
    settings = conf.get_settings(branch.company)
    times = services.storage_times(settings.storage_times if times is None else times)
    positions = list(positions) or default_positions(branch)
    if not positions:
        raise DomainError(_("Nobody works at this branch yet: pick who takes the readings."))
    for position in positions:
        if position.company_id != by.company_id:
            raise DomainError(_("That isn't part of your company."))
    have = set(
        TaskTemplate.objects.for_company(branch.company_id)
        .filter(branch=branch, personal=False, onboarding=False)
        .values_list("title", "due_time")
    )
    result = PresetResult()
    for plan in plans(branch, fridges=fridges, times=times, settings=settings):
        if (plan["title"], plan["due_time"]) in have:
            result.existing.append(plan["title"])
            continue
        result.created.append(
            services.create_template(by=by, branch=branch, positions=positions, shared=True, **plan)
        )
    audit.record(
        TasksAction.STORAGE_PRESET,
        company_id=branch.company_id,
        actor=by.user,
        target=branch,
        fridges=fridges,
        times=[moment.strftime("%H:%M") for moment in times],
        created=len(result.created),
    )
    return result
