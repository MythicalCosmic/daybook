"""Audit action codes and labels of hiring (registered by `apps.hr.hiring.hooks`).

Vacancies are recorded against the vacancy, everything about an application against the
applicant ("vacancy" and "applicant" targets, whose History tab `hr.hiring` opens).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HiringAction(models.TextChoices):
    VACANCY_CREATED = "hr.vacancy_created", _("Created a vacancy")
    VACANCY_CHANGED = "hr.vacancy_changed", _("Changed a vacancy")
    VACANCY_OPENED = "hr.vacancy_opened", _("Opened a vacancy to applicants")
    VACANCY_PAUSED = "hr.vacancy_paused", _("Paused a vacancy")
    VACANCY_CLOSED = "hr.vacancy_closed", _("Closed a vacancy")
    VACANCY_DELETED = "hr.vacancy_deleted", _("Deleted a vacancy")
    APPLIED = "hr.applicant_applied", _("Applied for a vacancy")
    APPLICANT_MOVED = "hr.applicant_moved", _("Moved an applicant to another stage")
    APPLICANT_REJECTED = "hr.applicant_rejected", _("Turned down an applicant")
    APPLICANT_HIRED = "hr.applicant_hired", _("Hired an applicant")
    APPLICANT_NOTED = "hr.applicant_noted", _("Added a note about an applicant")
