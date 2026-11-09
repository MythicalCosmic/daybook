"""Certificates of finished courses (docs/PLAN-LEARNING.md §4.4): a PDF in the person's language
(uz, ru or en) with the company, the person, the course, the date, the number, the end of its
validity for courses that renew, and the manager's line.

It is made once, when the course is finished (`issued`, after the commit), and kept in private
storage (`Assignment.certificate_file`); downloads are signed links (the file check
`learning.certificate`: the person themselves, even while suspended, and holders of
`learning.view` who see them).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import pdf
from apps.core.files import signed_url
from apps.learning import conf, notify_courses, queries
from apps.learning.models import Assignment
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

TEMPLATE = "learning/certificate.html"
LINK_TTL = 60 * 60


def _date(company, moment) -> str:
    return queries.local_day(company, moment).strftime("%d.%m.%Y") if moment else ""


def manager_name(member: Membership) -> str:
    """Who signs: the person's head, else their branch's manager, else nobody (a blank line)."""
    from apps.members.departments import manager_of

    head = manager_of(member)
    if head is not None:
        return str(head)
    branch = member.home_branch
    if branch is not None and branch.manager_id and branch.manager_id != member.pk:
        return str(branch.manager)
    return ""


def context(assignment: Assignment) -> dict:
    company = assignment.company
    member = assignment.membership
    return {
        "company": company,
        "title": _("Certificate"),
        "printed_on": _date(company, assignment.completed_at),
        "logo_src": pdf.image_src(company.logo) if company.logo else "",
        "person": str(member),
        "position": member.position.name if member.position_id else "",
        "course": assignment.course.title,
        "completed_on": _date(company, assignment.completed_at),
        "number": assignment.certificate_no,
        "valid_until": _date(company, assignment.expires_at),
        "manager": manager_name(member),
    }


def language_of(member: Membership) -> str:
    language = getattr(member.user, "language", "") or member.company.default_language
    return language if language in ("uz", "ru", "en") else "uz"


def render(assignment: Assignment, *, language: str) -> bytes:
    return pdf.render_pdf(TEMPLATE, context(assignment), language=language)


def _rows():
    return Assignment.objects.select_related(
        "company", "course", "membership__user", "membership__position", "membership__home_branch"
    )


def ensure_pdf(assignment: Assignment):
    """The stored PDF (made now when missing), or None without a certificate."""
    if assignment.state != Assignment.State.COMPLETED or not assignment.certificate_no:
        return None
    if assignment.certificate_file and assignment.certificate_file.storage.exists(
        assignment.certificate_file.name
    ):
        return assignment.certificate_file
    assignment = _rows().get(pk=assignment.pk)
    data = render(assignment, language=language_of(assignment.membership))
    with transaction.atomic():
        locked = Assignment.objects.select_for_update().get(pk=assignment.pk)
        if locked.certificate_file and locked.certificate_file.storage.exists(
            locked.certificate_file.name
        ):
            return locked.certificate_file
        locked.certificate_file.save(f"{uuid4().hex}.pdf", ContentFile(data), save=False)
        locked.save(update_fields=["certificate_file", "updated_at"])
    return locked.certificate_file


def file_name(assignment: Assignment) -> str:
    return f"{assignment.certificate_no or 'certificate'}.pdf"


def link(assignment: Assignment, *, user) -> str | None:
    """A signed link to the stored PDF, or None (no certificate, or not made yet)."""
    if assignment.state != Assignment.State.COMPLETED or not assignment.certificate_no:
        return None
    if not assignment.certificate_file:
        return None
    return signed_url(
        assignment.certificate_file,
        user=user,
        company_id=assignment.company_id,
        check=f"learning.certificate:{assignment.pk}",
        ttl=LINK_TTL,
        filename=file_name(assignment),
    )


def issued(assignment_id: int) -> None:
    """After a course with a certificate is finished: make the PDF, tell the person."""
    assignment = _rows().filter(pk=assignment_id).first()
    if assignment is None or not assignment.certificate_no:
        return
    try:
        ensure_pdf(assignment)
    except Exception:
        logger.exception("The certificate of assignment %s couldn't be made", assignment_id)
    notify_courses.certificate(assignment)


def may_open(user, company_id: int, assignment_id: int) -> bool:
    """The file check `learning.certificate`."""
    from apps.members.queries import in_scope

    assignment = (
        Assignment.objects.select_related("membership", "company")
        .filter(company_id=company_id, pk=assignment_id)
        .first()
    )
    if assignment is None or not conf.is_on(assignment.company):
        return False
    if assignment.membership.user_id == user.pk:
        return True
    viewer = (
        Membership.objects.select_related("role", "company")
        .filter(user=user, company_id=company_id, status=Membership.Status.APPROVED)
        .first()
    )
    return (
        viewer is not None
        and viewer.has_perm(Perm.LEARNING_VIEW)
        and in_scope(viewer, assignment.membership)
    )
