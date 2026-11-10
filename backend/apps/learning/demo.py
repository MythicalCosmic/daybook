"""Demo data of learning: courses and lessons first (Q1), then quizzes, answers, checks and the
tutor's suggestions (Q2), which read them, then the tutor chat's drafts waiting for approval
(v11-h)."""

from apps.learning import demo_courses, demo_quizzes, demo_tutor


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    demo_courses.seed(company, people, now)
    demo_quizzes.seed(company, people, now)
    demo_tutor.seed(company, people, now)
