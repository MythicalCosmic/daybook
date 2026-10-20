from rest_framework import exceptions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.exceptions import DomainError


class DomainRuleViolated(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"


def exception_handler(exc, context):
    """DRF's handler, plus DomainError -> 400 carrying its user-safe message."""
    if isinstance(exc, DomainError):
        exc = DomainRuleViolated(str(exc))
    return drf_exception_handler(exc, context)


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
