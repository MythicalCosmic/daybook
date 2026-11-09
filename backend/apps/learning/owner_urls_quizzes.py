"""Owner endpoints of package Q2 (quizzes, the daily question, checks, skills, the tutor),
mounted at `/api/v1/owner/companies/<int:company_id>/` through `owner_urls.py`."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.learning import owner_api_quizzes as api

router = SimpleRouter()
router.register("learning/questions", api.QuestionViewSet, basename="owner-learning-question")
router.register("learning/quizzes", api.QuizViewSet, basename="owner-learning-quiz")
router.register("learning/checks", api.CheckViewSet, basename="owner-learning-check")
router.register("learning/suggestions", api.SuggestionViewSet, basename="owner-learning-suggestion")
router.register("learning/drafts", api.DraftViewSet, basename="owner-learning-draft")

urlpatterns = [
    path(
        "learning/questions/images/",
        api.ImageView.as_view(),
        name="owner-learning-question-images",
    ),
    path(
        "learning/questions/daily/",
        api.DailySettingsView.as_view(),
        name="owner-learning-daily",
    ),
    path("learning/attempts/<int:pk>/", api.AttemptView.as_view(), name="owner-learning-attempt"),
    path("learning/skills/", api.SkillsView.as_view(), name="owner-learning-skills"),
    path("learning/tutor/", api.TutorView.as_view(), name="owner-learning-tutor"),
    path(
        "learning/tutor/conversations/",
        api.TutorConversationsView.as_view(),
        name="owner-learning-tutor-conversations",
    ),
    path(
        "learning/skills/<int:member_id>/",
        api.PersonSkillsView.as_view(),
        name="owner-learning-person-skills",
    ),
    *router.urls,
]
