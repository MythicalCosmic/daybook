"""Unchangeable lists ("O‘zgarmas ro‘yxat"): a study register kept like a bound journal.

A list has numbered topics (rows) and numbered students (columns: members of the company, or
typed-in names such as interns from a college). A **line** (`StudyMark`) says a student studied a
topic on a day. Lines are only ever added:

- a line is never edited or deleted. A mistake is taken back by a **correction** line with its
  reason; the cell is then empty again and can be marked anew;
- topics and students can be renamed or removed only until a line mentions them;
- **sealing** is final: nothing is added afterwards, and the seal keeps a digest of the last line.

Each line's `digest` is a SHA-256 of the line before it and of its own content (with the topic's
and the student's number and name), so `verify` notices a row changed in the database behind the
app's back. Writes lock the list's row, so two people marking at once still make one unbroken chain.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date

from django.db import transaction
from django.db.models import Count, Max, Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch, Company
from apps.console.ranges import company_today
from apps.core.exceptions import DomainError
from apps.learning.audit_actions import ListAction
from apps.learning.models import StudyList, StudyMark, StudyStudent, StudyTopic
from apps.members.models import Membership

GENESIS = "0" * 64
MAX_TITLE = 200
MAX_TOPIC = 300
MAX_NAME = 200
MAX_NOTE = 300
MAX_TOPICS = 300
MAX_STUDENTS = 200
SEP = "\x1f"


# Helpers ----------------------------------------------------------------------------------


def _squash(value: str | None) -> str:
    return " ".join((value or "").split())


def _text(value: str | None, *, limit: int, empty: str) -> str:
    text = _squash(value)
    if not text:
        raise DomainError(empty)
    if len(text) > limit:
        raise DomainError(_("Keep it under %(n)d characters.") % {"n": limit})
    return text


def _optional(value: str | None, *, limit: int) -> str:
    text = _squash(value)
    if len(text) > limit:
        raise DomainError(_("Keep it under %(n)d characters.") % {"n": limit})
    return text


def member_name(member: Membership | None) -> str:
    if member is None:
        return ""
    return (member.full_name or str(member.user))[:MAX_NAME]


def _audit(action: str, study_list: StudyList, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=study_list.company_id,
        actor=by.user if by is not None else None,
        target=study_list,
        **details,
    )


def _must_be_open(study_list: StudyList) -> None:
    if study_list.state != StudyList.State.OPEN:
        raise DomainError(_("This list is sealed: nothing can be added or changed."))


def _lock(study_list: StudyList) -> StudyList:
    """The list's row, locked until the transaction ends: writes to one list go one at a time."""
    return StudyList.objects.select_for_update().get(pk=study_list.pk)


def _check_branch(company: Company, branch: Branch | None) -> None:
    if branch is not None and branch.company_id != company.pk:
        raise DomainError(_("Pick a branch of this company."))


# Digests ----------------------------------------------------------------------------------


def line_digest(
    previous: str,
    *,
    list_id: int,
    number: int,
    kind: str,
    topic: StudyTopic,
    student: StudyStudent,
    studied_on: date | None,
    note: str,
    corrects_number: int | None,
    written_by_name: str,
) -> str:
    parts = [
        previous,
        str(list_id),
        str(number),
        kind,
        f"{topic.number}:{topic.title}",
        f"{student.number}:{student.name}",
        studied_on.isoformat() if studied_on else "",
        note,
        str(corrects_number or ""),
        written_by_name,
    ]
    return hashlib.sha256(SEP.join(parts).encode()).hexdigest()


def seal_digest(study_list: StudyList, last_digest: str, *, topics: int, students: int) -> str:
    parts = ["seal", str(study_list.pk), study_list.title, last_digest, str(topics), str(students)]
    return hashlib.sha256(SEP.join(parts).encode()).hexdigest()


def verify(
    study_list: StudyList,
    marks: Sequence[StudyMark],
    topics: dict[int, StudyTopic],
    students: dict[int, StudyStudent],
) -> bool:
    """Whether the lines (oldest first) still chain up, and the seal with them."""
    previous = GENESIS
    numbers = {}
    for expected, mark in enumerate(marks, start=1):
        topic, student = topics.get(mark.topic_id), students.get(mark.student_id)
        if mark.number != expected or topic is None or student is None:
            return False
        corrects_number = numbers.get(mark.corrects_id) if mark.corrects_id else None
        if mark.corrects_id and corrects_number is None:
            return False
        digest = line_digest(
            previous,
            list_id=study_list.pk,
            number=mark.number,
            kind=mark.kind,
            topic=topic,
            student=student,
            studied_on=mark.studied_on,
            note=mark.note,
            corrects_number=corrects_number,
            written_by_name=mark.written_by_name,
        )
        if digest != mark.digest:
            return False
        numbers[mark.pk] = mark.number
        previous = mark.digest
    if study_list.state == StudyList.State.SEALED:
        return study_list.seal_digest == seal_digest(
            study_list, previous, topics=len(topics), students=len(students)
        )
    return True


# Lists ------------------------------------------------------------------------------------


def create_list(
    company: Company,
    *,
    by: Membership,
    title: str,
    description: str = "",
    teacher: str = "",
    branch: Branch | None = None,
) -> StudyList:
    _check_branch(company, branch)
    with transaction.atomic():
        study_list = StudyList.objects.create(
            company=company,
            title=_text(title, limit=MAX_TITLE, empty=_("Give the list a title.")),
            description=(description or "").strip(),
            teacher=_optional(teacher, limit=MAX_NAME),
            branch=branch,
            created_by=by,
        )
        _audit(ListAction.CREATED, study_list, by)
    return study_list


UNSET = object()


def update_list(
    study_list: StudyList,
    *,
    by: Membership,
    title=UNSET,
    description=UNSET,
    teacher=UNSET,
    branch=UNSET,
) -> StudyList:
    with transaction.atomic():
        study_list = _lock(study_list)
        _must_be_open(study_list)
        if title is not UNSET:
            study_list.title = _text(title, limit=MAX_TITLE, empty=_("Give the list a title."))
        if description is not UNSET:
            study_list.description = (description or "").strip()
        if teacher is not UNSET:
            study_list.teacher = _optional(teacher, limit=MAX_NAME)
        if branch is not UNSET:
            _check_branch(study_list.company, branch)
            study_list.branch = branch
        study_list.save()
        _audit(ListAction.CHANGED, study_list, by)
    return study_list


def delete_list(study_list: StudyList, *, by: Membership) -> None:
    with transaction.atomic():
        study_list = _lock(study_list)
        if study_list.marks.exists():
            raise DomainError(_("A list with lines can't be deleted; it can only be sealed."))
        _audit(ListAction.DELETED, study_list, by, title=study_list.title)
        study_list.delete()


def seal(study_list: StudyList, *, by: Membership) -> StudyList:
    with transaction.atomic():
        study_list = _lock(study_list)
        _must_be_open(study_list)
        last = study_list.marks.order_by("-number").first()
        study_list.state = StudyList.State.SEALED
        study_list.sealed_at = timezone.now()
        study_list.sealed_by = by
        study_list.seal_digest = seal_digest(
            study_list,
            last.digest if last else GENESIS,
            topics=study_list.topics.count(),
            students=study_list.students.count(),
        )
        study_list.save()
        _audit(ListAction.SEALED, study_list, by, digest=study_list.seal_digest)
    return study_list


# Topics and students -------------------------------------------------------------------------


def add_topics(study_list: StudyList, *, by: Membership, titles: Iterable[str]) -> None:
    cleaned = [_text(t, limit=MAX_TOPIC, empty=_("A topic needs a title.")) for t in titles]
    if not cleaned:
        raise DomainError(_("Write at least one topic."))
    with transaction.atomic():
        study_list = _lock(study_list)
        _must_be_open(study_list)
        last = study_list.topics.aggregate(n=Max("number"))["n"] or 0
        if study_list.topics.count() + len(cleaned) > MAX_TOPICS:
            raise DomainError(_("A list holds at most %(n)d topics.") % {"n": MAX_TOPICS})
        StudyTopic.objects.bulk_create(
            StudyTopic(
                company_id=study_list.company_id, study_list=study_list, number=last + i, title=t
            )
            for i, t in enumerate(cleaned, start=1)
        )


def _unlocked_topic(study_list: StudyList, topic_id: int) -> StudyTopic:
    _must_be_open(study_list)
    topic = study_list.topics.filter(pk=topic_id).first()
    if topic is None:
        raise DomainError(_("There's no such topic in this list."))
    if topic.marks.exists():
        raise DomainError(_("This topic already has lines, so it can't be changed."))
    return topic


def rename_topic(study_list: StudyList, *, by: Membership, topic_id: int, title: str) -> None:
    with transaction.atomic():
        study_list = _lock(study_list)
        topic = _unlocked_topic(study_list, topic_id)
        topic.title = _text(title, limit=MAX_TOPIC, empty=_("A topic needs a title."))
        topic.save()


def remove_topic(study_list: StudyList, *, by: Membership, topic_id: int) -> None:
    with transaction.atomic():
        study_list = _lock(study_list)
        _unlocked_topic(study_list, topic_id).delete()


def add_students(
    study_list: StudyList,
    *,
    by: Membership,
    members: Iterable[Membership] = (),
    names: Iterable[tuple[str, str]] = (),
) -> None:
    members, names = list(members), list(names)
    if not members and not names:
        raise DomainError(_("Pick people or type a name."))
    typed = [
        (
            _text(name, limit=MAX_NAME, empty=_("Type the student's name.")),
            _optional(note, limit=MAX_NAME),
        )
        for name, note in names
    ]
    with transaction.atomic():
        study_list = _lock(study_list)
        _must_be_open(study_list)
        on_list = set(
            study_list.students.exclude(membership=None).values_list("membership_id", flat=True)
        )
        rows = []
        for member in members:
            if member.company_id != study_list.company_id:
                raise DomainError(_("Pick people of this company."))
            if member.pk in on_list:
                continue
            on_list.add(member.pk)
            rows.append(StudyStudent(membership=member, name=member_name(member) or "—"))
        rows += [StudyStudent(name=name, note=note) for name, note in typed]
        if study_list.students.count() + len(rows) > MAX_STUDENTS:
            raise DomainError(_("A list holds at most %(n)d students.") % {"n": MAX_STUDENTS})
        last = study_list.students.aggregate(n=Max("number"))["n"] or 0
        for i, row in enumerate(rows, start=1):
            row.company_id = study_list.company_id
            row.study_list = study_list
            row.number = last + i
        StudyStudent.objects.bulk_create(rows)


def _unlocked_student(study_list: StudyList, student_id: int) -> StudyStudent:
    _must_be_open(study_list)
    student = study_list.students.filter(pk=student_id).first()
    if student is None:
        raise DomainError(_("There's no such student in this list."))
    if student.marks.exists():
        raise DomainError(_("This student already has lines, so they can't be changed."))
    return student


def edit_student(
    study_list: StudyList, *, by: Membership, student_id: int, name=UNSET, note=UNSET
) -> None:
    with transaction.atomic():
        study_list = _lock(study_list)
        student = _unlocked_student(study_list, student_id)
        if name is not UNSET:
            student.name = _text(name, limit=MAX_NAME, empty=_("Type the student's name."))
        if note is not UNSET:
            student.note = _optional(note, limit=MAX_NAME)
        student.save()


def remove_student(study_list: StudyList, *, by: Membership, student_id: int) -> None:
    with transaction.atomic():
        study_list = _lock(study_list)
        _unlocked_student(study_list, student_id).delete()


# Lines ------------------------------------------------------------------------------------


def standing(study_list: StudyList, topic_id: int, student_id: int) -> StudyMark | None:
    """The cell's "studied" line that no correction took back, if any."""
    return StudyMark.objects.filter(
        study_list=study_list,
        topic_id=topic_id,
        student_id=student_id,
        kind=StudyMark.Kind.STUDIED,
        corrections__isnull=True,
    ).first()


def _append(study_list: StudyList, mark: StudyMark, *, corrects_number: int | None) -> StudyMark:
    last = StudyMark.objects.filter(study_list=study_list).order_by("-number").first()
    mark.company_id = study_list.company_id
    mark.study_list = study_list
    mark.number = (last.number if last else 0) + 1
    mark.digest = line_digest(
        last.digest if last else GENESIS,
        list_id=study_list.pk,
        number=mark.number,
        kind=mark.kind,
        topic=mark.topic,
        student=mark.student,
        studied_on=mark.studied_on,
        note=mark.note,
        corrects_number=corrects_number,
        written_by_name=mark.written_by_name,
    )
    mark.save()
    return mark


def write_mark(
    study_list: StudyList,
    *,
    by: Membership,
    topic_id: int,
    student_id: int,
    studied_on: date | None = None,
    note: str = "",
) -> StudyMark:
    today = company_today(study_list.company)
    studied_on = studied_on or today
    if studied_on > today:
        raise DomainError(_("The day can't be in the future."))
    note = _optional(note, limit=MAX_NOTE)
    with transaction.atomic():
        study_list = _lock(study_list)
        _must_be_open(study_list)
        topic = study_list.topics.filter(pk=topic_id).first()
        student = study_list.students.filter(pk=student_id).first()
        if topic is None or student is None:
            raise DomainError(_("Pick a topic and a student of this list."))
        if standing(study_list, topic.pk, student.pk) is not None:
            raise DomainError(
                _("This student already has a line for this topic. Correct it first if it's wrong.")
            )
        mark = _append(
            study_list,
            StudyMark(
                kind=StudyMark.Kind.STUDIED,
                topic=topic,
                student=student,
                studied_on=studied_on,
                note=note,
                written_by=by,
                written_by_name=member_name(by),
            ),
            corrects_number=None,
        )
        _audit(ListAction.LINE_WRITTEN, study_list, by, line=mark.number)
    return mark


def correct_mark(study_list: StudyList, *, by: Membership, mark_id: int, reason: str) -> StudyMark:
    reason = _squash(reason)
    if len(reason) < 3:
        raise DomainError(_("Write why this line is wrong."))
    if len(reason) > MAX_NOTE:
        raise DomainError(_("Keep it under %(n)d characters.") % {"n": MAX_NOTE})
    with transaction.atomic():
        study_list = _lock(study_list)
        _must_be_open(study_list)
        target = (
            StudyMark.objects.filter(study_list=study_list, pk=mark_id)
            .select_related("topic", "student")
            .first()
        )
        if target is None:
            raise DomainError(_("There's no such line in this list."))
        if (
            target.kind != StudyMark.Kind.STUDIED
            or StudyMark.objects.filter(corrects=target).exists()
        ):
            raise DomainError(_("Only a line that still stands can be corrected."))
        mark = _append(
            study_list,
            StudyMark(
                kind=StudyMark.Kind.CORRECTION,
                topic=target.topic,
                student=target.student,
                note=reason,
                corrects=target,
                written_by=by,
                written_by_name=member_name(by),
            ),
            corrects_number=target.number,
        )
        _audit(ListAction.LINE_CORRECTED, study_list, by, line=mark.number, corrects=target.number)
    return mark


# Reading ----------------------------------------------------------------------------------


def visible(company: Company, branch_ids: list[int] | None) -> QuerySet[StudyList]:
    """The company's lists the caller sees: whole-company lists, and those of their branches."""
    lists = StudyList.objects.filter(company=company)
    if branch_ids is not None:
        lists = lists.filter(Q(branch__isnull=True) | Q(branch_id__in=branch_ids))
    return lists


def _branch(study_list: StudyList) -> dict | None:
    if study_list.branch_id is None:
        return None
    return {"id": study_list.branch_id, "name": study_list.branch.name}


def rows(lists: QuerySet[StudyList]) -> list[dict]:
    lists = lists.select_related("branch").annotate(
        n_topics=Count("topics", distinct=True),
        n_students=Count("students", distinct=True),
        n_studied=Count(
            "marks",
            filter=Q(marks__kind=StudyMark.Kind.STUDIED, marks__corrections__isnull=True),
            distinct=True,
        ),
    )
    return [
        {
            "id": row.pk,
            "title": row.title,
            "teacher": row.teacher,
            "branch": _branch(row),
            "state": row.state,
            "topics": row.n_topics,
            "students": row.n_students,
            "studied": row.n_studied,
            "cells": row.n_topics * row.n_students,
            "created_at": row.created_at,
            "sealed_at": row.sealed_at,
        }
        for row in lists
    ]


def detail(study_list: StudyList) -> dict:
    study_list = (
        StudyList.objects.select_related("branch", "created_by__user", "sealed_by__user")
        .filter(pk=study_list.pk)
        .get()
    )
    topics = list(study_list.topics.all())
    students = list(study_list.students.select_related("membership__position"))
    marks = list(StudyMark.objects.filter(study_list=study_list).order_by("number"))
    used_topics = {m.topic_id for m in marks}
    used_students = {m.student_id for m in marks}
    corrected_by = {m.corrects_id: m.pk for m in marks if m.corrects_id}
    intact = verify(study_list, marks, {t.pk: t for t in topics}, {s.pk: s for s in students})
    return {
        "id": study_list.pk,
        "title": study_list.title,
        "description": study_list.description,
        "teacher": study_list.teacher,
        "branch": _branch(study_list),
        "state": study_list.state,
        "created_at": study_list.created_at,
        "created_by": member_name(study_list.created_by),
        "sealed_at": study_list.sealed_at,
        "sealed_by": member_name(study_list.sealed_by),
        "seal_digest": study_list.seal_digest,
        "intact": intact,
        "topics": [
            {"id": t.pk, "number": t.number, "title": t.title, "locked": t.pk in used_topics}
            for t in topics
        ],
        "students": [
            {
                "id": s.pk,
                "number": s.number,
                "name": s.name,
                "note": s.note,
                "member_id": s.membership_id,
                "position": (
                    s.membership.position.name
                    if s.membership_id and s.membership.position_id
                    else None
                ),
                "locked": s.pk in used_students,
            }
            for s in students
        ],
        "marks": [
            {
                "id": m.pk,
                "number": m.number,
                "kind": m.kind,
                "topic_id": m.topic_id,
                "student_id": m.student_id,
                "studied_on": m.studied_on,
                "note": m.note,
                "corrects_id": m.corrects_id,
                "corrected_by_id": corrected_by.get(m.pk),
                "written_by": m.written_by_name,
                "written_at": m.created_at,
                "digest": m.digest,
            }
            for m in marks
        ],
    }
