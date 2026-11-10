"""Equipment's owner endpoints, included by `apps/lifecycle/owner_urls.py`."""

from django.urls import path

from apps.lifecycle.equipment import owner_api

urlpatterns = [
    path("lifecycle/equipment/", owner_api.PeopleView.as_view(), name="lifecycle-equipment"),
    path(
        "lifecycle/equipment/items/",
        owner_api.ItemsView.as_view(),
        name="lifecycle-equipment-items",
    ),
    path(
        "lifecycle/equipment/categories/",
        owner_api.CategoriesView.as_view(),
        name="lifecycle-equipment-categories",
    ),
    path(
        "lifecycle/equipment/issue/",
        owner_api.IssueView.as_view(),
        name="lifecycle-equipment-issue",
    ),
    path(
        "lifecycle/equipment/handouts/<int:pk>/return/",
        owner_api.ReturnView.as_view(),
        name="lifecycle-equipment-return",
    ),
    path(
        "lifecycle/equipment/handouts/<int:pk>/deduction/",
        owner_api.DeductionView.as_view(),
        name="lifecycle-equipment-deduction",
    ),
    path(
        "lifecycle/people/<int:member_id>/equipment/",
        owner_api.PersonView.as_view(),
        name="lifecycle-equipment-person",
    ),
]
