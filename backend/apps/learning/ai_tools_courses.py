"""Read-only AI tools of package Q1 (courses, lessons, videos, who watched what), imported
by `ai_tools.py`.

Each wraps a query and registers with `apps.ai.tools.registry.ai_tool` (domain "learning",
feature "learning", perm `learning.view`; names start with `learning_`). People are branch-
scoped (`ToolContext.branch_ids`); names only, never a phone number or pay.
"""

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.learning import queries
from apps.learning.models import Course, Lesson, Status
from apps.members.permissions import Perm

DOMAIN = "learning"
FEATURE = "learning"


class CoursesInput(BaseModel):
    include_drafts: bool = Field(False, description="Also list courses not published yet.")


@ai_tool(
    "learning_courses",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "Training courses and mandatory training: each course with how many people have it, "
        "finished it, are on it or are late; who is late with mandatory training and by how many "
        "days"
    ),
    input=CoursesInput,
    feature=FEATURE,
)
def learning_courses(ctx: ToolContext, args: CoursesInput) -> ToolResult:
    company = ctx.company
    stats = queries.course_stats(company, branch_ids=ctx.branch_ids, now=ctx.now)
    courses = Course.objects.filter(company=company).exclude(status=Status.ARCHIVED)
    if not args.include_drafts:
        courses = courses.filter(status=Status.PUBLISHED)
    rows = [
        {
            "id": course.pk,
            "title": course.title,
            "status": course.status,
            "mandatory": course.mandatory,
            "days_to_finish": course.due_days,
            "renews_every_months": course.renew_months,
            **stats.get(course.pk, queries.EMPTY_STATS),
        }
        for course in courses.order_by("position", "pk")
    ]
    report = queries.compliance(company, branch_ids=ctx.branch_ids, now=ctx.now)
    return ToolResult(
        rows=rows,
        data={
            "mandatory_people": report.people,
            "mandatory_all_done": report.completed,
            "mandatory_late_people": report.overdue_people,
            "late": [
                {
                    "name": item.name,
                    "course": item.course_title,
                    "days_late": item.days_late,
                }
                for item in report.late[:20]
            ],
        },
        as_of=ctx.now,
    )


class CourseInput(BaseModel):
    course_id: int = Field(description="The course's id (from learning_courses).")


@ai_tool(
    "learning_course_people",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "One course's people: each person's progress (steps done of the required ones), deadline, "
        "days late, when they finished and their certificate number"
    ),
    input=CourseInput,
    feature=FEATURE,
)
def learning_course_people(ctx: ToolContext, args: CourseInput) -> ToolResult:
    course = Course.objects.filter(company=ctx.company, pk=args.course_id).first()
    if course is None:
        raise ToolNotFound
    rows = []
    for item in queries.course_people(course, branch_ids=ctx.branch_ids, now=ctx.now):
        row = item["assignment"]
        rows.append(
            {
                "id": row["id"],
                "name": item["member"]["name"],
                "position": item["member"]["position"],
                "branch": item["member"]["branch"],
                "state": row["state"],
                "steps_done": row["steps_done"],
                "steps_total": row["steps_total"],
                "due_at": row["due_at"].isoformat() if row["due_at"] else None,
                "days_late": row["days_late"],
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "certificate_no": row["certificate_no"] or None,
            }
        )
    return ToolResult(
        rows=rows,
        data={"course": course.title, "mandatory": course.mandatory},
        as_of=ctx.now,
    )


class LessonInput(BaseModel):
    lesson_id: int = Field(description="The video lesson's id.")


@ai_tool(
    "learning_lesson_viewers",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "Who watched a video lesson: everyone it is for, whether they never opened it, are "
        "watching (how much of it they really played) or watched it, the time spent and when"
    ),
    input=LessonInput,
    feature=FEATURE,
)
def learning_lesson_viewers(ctx: ToolContext, args: LessonInput) -> ToolResult:
    lesson = Lesson.objects.filter(company=ctx.company, pk=args.lesson_id).first()
    if lesson is None:
        raise ToolNotFound
    rows = [
        {
            "id": row["member"]["id"],
            "name": row["member"]["name"],
            "state": row["state"],
            "percent": row["percent"],
            "minutes_spent": round(row["spent_seconds"] / 60),
            "sessions": row["sessions"],
            "last_watched": row["last_at"].isoformat() if row["last_at"] else None,
            "watched_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }
        for row in queries.lesson_viewers(lesson, branch_ids=ctx.branch_ids)
    ]
    return ToolResult(
        rows=rows,
        data={"lesson": lesson.title, "length_seconds": lesson.duration_seconds},
        as_of=ctx.now,
    )


class PersonInput(BaseModel):
    member_id: int = Field(description="The person's membership id.")


@ai_tool(
    "learning_person",
    domain=DOMAIN,
    perm=Perm.LEARNING_VIEW,
    label=_(
        "One person's training: their courses (open, finished, late, certificates), the video "
        "lessons they watched and the knowledge base pages they read"
    ),
    input=PersonInput,
    feature=FEATURE,
)
def learning_person(ctx: ToolContext, args: PersonInput) -> ToolResult:
    member = (
        queries.people_in_scope(ctx.company, branch_ids=ctx.branch_ids)
        .filter(pk=args.member_id)
        .first()
    )
    if member is None:
        raise ToolNotFound
    found = queries.person_learning(member, now=timezone.now())
    return ToolResult(
        rows=[
            {
                "id": row["id"],
                "course": row["course"]["title"],
                "mandatory": row["course"]["mandatory"],
                "state": row["state"],
                "steps_done": row["steps_done"],
                "steps_total": row["steps_total"],
                "days_late": row["days_late"],
                "certificate_no": row["certificate_no"] or None,
            }
            for row in found["assignments"]
        ],
        data={
            "name": found["member"]["name"],
            "position": found["member"]["position"],
            "summary": found["summary"],
            "lessons": [
                {
                    "title": row["lesson"]["title"],
                    "percent": row["percent"],
                    "watched": row["completed_at"] is not None,
                }
                for row in found["lessons"][:30]
            ],
            "pages_read": [
                {"title": row["page"]["title"], "visits": row["visits"]}
                for row in found["pages"][:30]
            ],
        },
        as_of=ctx.now,
    )
