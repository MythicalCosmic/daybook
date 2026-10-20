from django.utils import translation
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework_simplejwt.authentication import JWTAuthentication


class LanguageJWTAuthentication(JWTAuthentication):
    """JWT login that also answers in the person's own language, as the bot does.

    LocaleMiddleware picks a language for every request first, so this choice never
    outlives the request.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _token = result
            translation.activate(user.language)
            request.LANGUAGE_CODE = translation.get_language()
        return result


class LanguageJWTScheme(SimpleJWTScheme):
    """Documents it in the API schema as the plain JWT login it is."""

    target_class = "apps.accounts.authentication.LanguageJWTAuthentication"
