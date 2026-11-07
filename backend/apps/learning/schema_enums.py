"""drf-spectacular enum names of learning, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string. Names start with
the app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "LearningStatusEnum": "apps.learning.models.Status",
    "LearningVideoStateEnum": "apps.learning.models.Video.State",
    "LearningLessonSourceEnum": "apps.learning.models.Lesson.Source",
    "LearningQuestionKindEnum": "apps.learning.models.Question.Kind",
    "LearningQuestionDifficultyEnum": "apps.learning.models.Question.Difficulty",
    "LearningQuestionStateEnum": "apps.learning.models.Question.State",
    "LearningQuestionSourceEnum": "apps.learning.models.Question.Source",
    "LearningQuizModeEnum": "apps.learning.models.Quiz.Mode",
    "LearningQuizShowAnswersEnum": "apps.learning.models.Quiz.ShowAnswers",
    "LearningStepKindEnum": "apps.learning.models.CourseStep.Kind",
    "LearningAssignmentStateEnum": "apps.learning.models.Assignment.State",
    "LearningAssignmentSourceEnum": "apps.learning.models.Assignment.Source",
    "LearningCheckEveryEnum": "apps.learning.models.RegularCheck.Every",
    "LearningCheckStateEnum": "apps.learning.models.RegularCheck.State",
    "LearningAttemptStateEnum": "apps.learning.models.Attempt.State",
    "LearningAnswerSourceEnum": "apps.learning.models.AnswerLog.Source",
    "LearningDraftJobStateEnum": "apps.learning.models.QuestionDraftJob.State",
    "LearningDraftEngineEnum": "apps.learning.models.QuestionDraftJob.Engine",
    "LearningSuggestionKindEnum": "apps.learning.models.TutorSuggestion.Kind",
    "LearningSuggestionStateEnum": "apps.learning.models.TutorSuggestion.State",
}
