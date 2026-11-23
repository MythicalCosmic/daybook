"""Refusals of Ko‘z with the HTTP status and the `code` the device API answers with
(`{"detail": "...", "code": "..."}`, docs/KOZ.md §3). Owner endpoints answer them the same way;
they are `DomainError`s, so anything else that calls the services shows the message."""

from apps.core.exceptions import DomainError


class VisionError(DomainError):
    status = 400
    code = "invalid"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class BadCode(VisionError):
    code = "bad_code"


class UnknownCamera(VisionError):
    status = 404
    code = "unknown_camera"


class NotFound(VisionError):
    status = 404
    code = "not_found"


class TooLarge(VisionError):
    status = 413
    code = "too_large"


class NoCamera(VisionError):
    status = 409
    code = "no_camera"
