"""Employee endpoints of policies, included by apps/hr/urls.py (under
`/api/v1/companies/<int:company_id>/`)."""

from django.urls import path

from apps.hr.policies import api

urlpatterns = [
    path("hr/policies/", api.MyPoliciesView.as_view(), name="hr-my-policies"),
    path("hr/policies/<int:pk>/", api.MyPolicyView.as_view(), name="hr-my-policy"),
    path("hr/policies/<int:pk>/file/", api.MyPolicyFileView.as_view(), name="hr-my-policy-file"),
    path(
        "hr/policies/versions/<int:pk>/acknowledge/",
        api.SignPolicyView.as_view(),
        name="hr-my-policy-acknowledge",
    ),
]
