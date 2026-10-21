"""Owner endpoints, mounted at `/api/v1/owner/companies/<int:company_id>/`.

An optional `root_urlpatterns` list is mounted at `/api/v1/owner/` instead, for the few
owner endpoints outside a company.
"""

from django.urls import path

from apps.projects import owner_api as v

P = "projects/<int:project_id>/"

urlpatterns = [
    path("projects/", v.ProjectListView.as_view(), name="projects-list"),
    path("projects/summary/", v.SummaryView.as_view(), name="projects-summary"),
    path("projects/people/", v.PeopleView.as_view(), name="projects-people"),
    path("projects/options/", v.OptionsView.as_view(), name="projects-options"),
    path("projects/roadmap/", v.RoadmapView.as_view(), name="projects-roadmap"),
    path("projects/settings/", v.SettingsView.as_view(), name="projects-settings"),
    path("projects/time/", v.TimeView.as_view(), name="projects-time"),
    path("projects/time/<int:entry_id>/", v.TimeDetailView.as_view(), name="projects-time-detail"),
    path("projects/timers/", v.TimersView.as_view(), name="projects-timers"),
    path("projects/timers/stop/", v.TimerStopView.as_view(), name="projects-timer-stop"),
    path(P, v.ProjectDetailView.as_view(), name="projects-detail"),
    path(P + "archive/", v.ArchiveView.as_view(), name="projects-archive"),
    path(P + "restore/", v.ArchiveView.as_view(restore=True), name="projects-restore"),
    path(P + "schedule/", v.RoadmapScheduleView.as_view(), name="projects-schedule"),
    path(P + "board/", v.BoardView.as_view(), name="projects-board"),
    path(P + "cards/", v.CardListView.as_view(), name="projects-cards"),
    path(P + "cards/<int:task_id>/", v.CardDetailView.as_view(), name="projects-card"),
    path(P + "cards/<int:task_id>/move/", v.CardMoveView.as_view(), name="projects-card-move"),
    path(
        P + "cards/<int:task_id>/schedule/",
        v.CardScheduleView.as_view(),
        name="projects-card-schedule",
    ),
    path(P + "lists/", v.ListsView.as_view(), name="projects-lists"),
    path(P + "lists/reorder/", v.ListReorderView.as_view(), name="projects-lists-reorder"),
    path(P + "lists/<int:list_id>/", v.ListDetailView.as_view(), name="projects-list-detail"),
    path(P + "milestones/", v.MilestonesView.as_view(), name="projects-milestones"),
    path(
        P + "milestones/<int:milestone_id>/",
        v.MilestoneDetailView.as_view(),
        name="projects-milestone",
    ),
    path(P + "labels/", v.LabelsView.as_view(), name="projects-labels"),
    path(P + "labels/<int:label_id>/", v.LabelDetailView.as_view(), name="projects-label"),
    path(P + "members/", v.MembersView.as_view(), name="projects-members"),
    path(P + "members/<int:row_id>/", v.MemberDetailView.as_view(), name="projects-member"),
    path(P + "updates/", v.UpdatesView.as_view(), name="projects-updates"),
    path(P + "files/", v.FilesView.as_view(), name="projects-files"),
    path(P + "files/<int:file_id>/", v.FileDetailView.as_view(), name="projects-file"),
    path(P + "links/", v.LinksView.as_view(), name="projects-links"),
    path(P + "links/<int:link_id>/", v.LinkDetailView.as_view(), name="projects-link"),
    path(P + "financials/", v.FinancialsView.as_view(), name="projects-financials"),
    path(P + "expenses/", v.ExpenseView.as_view(), name="projects-expenses"),
    path(P + "expense-options/", v.ExpenseOptionsView.as_view(), name="projects-expense-options"),
    path(P + "timeline/", v.TimelineView.as_view(), name="projects-timeline"),
]
