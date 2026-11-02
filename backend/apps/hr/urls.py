"""Employee endpoints, mounted at `/api/v1/companies/<int:company_id>/`."""

from django.urls import path

from apps.hr import api

urlpatterns = [
    path("hr/profile/", api.MyProfileView.as_view(), name="hr-my-profile"),
    path(
        "hr/profile/emergency-contacts/",
        api.MyContactsView.as_view(),
        name="hr-my-emergency-contacts",
    ),
    path(
        "hr/profile/emergency-contacts/<int:pk>/",
        api.MyContactView.as_view(),
        name="hr-my-emergency-contact",
    ),
    path("hr/documents/", api.MyDocumentsView.as_view(), name="hr-my-documents"),
    path("hr/celebrations/", api.CelebrationsView.as_view(), name="hr-my-celebrations"),
    path("hr/contract/", api.MyContractView.as_view(), name="hr-my-contract"),
    path("hr/contract/pdf/", api.MyContractPdfView.as_view(), name="hr-my-contract-pdf"),
    path(
        "hr/contract/<int:pk>/acknowledge/",
        api.AcknowledgeContractView.as_view(),
        name="hr-my-contract-acknowledge",
    ),
]
