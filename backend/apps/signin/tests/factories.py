"""factory_boy factories for the models of owner sign-in."""

import hashlib
import secrets
from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import UserFactory
from apps.signin.models import DeviceSession, LoginLink, SignupCode


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class DeviceSessionFactory(DjangoModelFactory):
    class Meta:
        model = DeviceSession

    user = factory.SubFactory(UserFactory)
    refresh_jti = factory.LazyFunction(lambda: secrets.token_hex(16))
    user_agent = "Mozilla/5.0 (Windows NT 10.0) Chrome/140.0"
    ip = "213.230.1.2"


class LoginLinkFactory(DjangoModelFactory):
    class Meta:
        model = LoginLink

    code_hash = factory.LazyFunction(lambda: sha256(secrets.token_urlsafe(32)))
    poll_hash = factory.LazyFunction(lambda: sha256(secrets.token_urlsafe(32)))
    match_code = "47"
    bot = LoginLink.Bot.OWNER
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(minutes=3))


class SignupCodeFactory(DjangoModelFactory):
    class Meta:
        model = SignupCode

    code_hash = factory.LazyFunction(lambda: sha256(secrets.token_urlsafe(16)))
