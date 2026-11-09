"""Employee endpoints of package Q2 (quizzes, the daily question, checks, skills, the tutor),
mounted at `/api/v1/companies/<int:company_id>/` through `urls.py`."""

from django.urls import path

from apps.learning import api_quizzes as api

urlpatterns = [
    path("learning/quizzes/<int:pk>/", api.QuizView.as_view(), name="learning-quiz"),
    path(
        "learning/quizzes/<int:pk>/attempts/",
        api.StartAttemptView.as_view(),
        name="learning-quiz-attempts",
    ),
    path("learning/attempts/<int:pk>/", api.AttemptView.as_view(), name="learning-attempt"),
    path(
        "learning/attempts/<int:pk>/answers/",
        api.SaveAnswerView.as_view(),
        name="learning-attempt-answers",
    ),
    path(
        "learning/attempts/<int:pk>/finish/",
        api.FinishAttemptView.as_view(),
        name="learning-attempt-finish",
    ),
    path("learning/daily/", api.DailyView.as_view(), name="learning-daily"),
    path(
        "learning/daily/<int:pk>/answer/",
        api.DailyAnswerView.as_view(),
        name="learning-daily-answer",
    ),
    path("learning/checks/", api.ChecksView.as_view(), name="learning-checks"),
]
