"""Owner dashboard tokens: simplejwt tokens with `aud="dashboard"` and their own token types.

- `OwnerAccessToken` (15 minutes, `OWNER_ACCESS_TOKEN_LIFETIME`): the only token
  `OwnerJWTAuthentication` accepts. Desktop ones carry `sid`, the `DeviceSession` id.
- `OwnerRefreshToken` (7 days): lives in an httpOnly cookie on the desktop, rotates on every
  refresh and is blacklisted afterwards. Never issued inside Telegram.

The audience is written and checked by a token backend of their own, so a mini app token (no
`aud`) never opens `/api/v1/owner/…`; and the token types differ from simplejwt's `access` and
`refresh`, so an owner token never opens the mini app API either.
"""

from functools import cache

from django.conf import settings
from rest_framework_simplejwt.backends import TokenBackend
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token

AUDIENCE = "dashboard"
SESSION_CLAIM = "sid"


@cache
def owner_token_backend() -> TokenBackend:
    """simplejwt's backend with the dashboard audience: added on encode, required on decode."""
    return TokenBackend(
        api_settings.ALGORITHM,
        api_settings.SIGNING_KEY,
        api_settings.VERIFYING_KEY,
        audience=AUDIENCE,
        issuer=api_settings.ISSUER,
        jwk_url=api_settings.JWK_URL,
        leeway=api_settings.LEEWAY,
        json_encoder=api_settings.JSON_ENCODER,
    )


class _OwnerBackend:
    @property
    def token_backend(self) -> TokenBackend:
        return owner_token_backend()

    def get_token_backend(self) -> TokenBackend:
        return owner_token_backend()


class OwnerAccessToken(_OwnerBackend, Token):
    token_type = "owner_access"

    @property
    def lifetime(self):
        return settings.OWNER_ACCESS_TOKEN_LIFETIME


class OwnerRefreshToken(_OwnerBackend, RefreshToken):
    """Blacklistable (simplejwt's `token_blacklist` app); `.access_token` copies `sid`."""

    token_type = "owner_refresh"
    access_token_class = OwnerAccessToken
