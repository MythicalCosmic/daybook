"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`: courses and lessons
(Q1, `urls_courses.py`), then quizzes, the daily question and checks (Q2, `urls_quizzes.py`)."""

from apps.learning import urls_courses, urls_quizzes

urlpatterns = [*urls_courses.urlpatterns, *urls_quizzes.urlpatterns]
