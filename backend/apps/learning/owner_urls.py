"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`: courses, lessons and
videos (Q1, `owner_urls_courses.py`), then quizzes, checks, skills and the tutor (Q2,
`owner_urls_quizzes.py`)."""

from apps.learning import owner_urls_courses, owner_urls_quizzes

urlpatterns = [*owner_urls_courses.urlpatterns, *owner_urls_quizzes.urlpatterns]
