"""The daily look at upkeep: warranties, services, official instrument checks and insurance
coming up (`AssetSettings.remind_days` ahead; services a week ahead) and on or after their day.
Runs every hour and speaks from 08:00 company time; each notice goes out once."""

from datetime import timedelta

from django.utils import timezone

from apps.assets import conf, notify, posting
from apps.assets.models import Asset, Permit
from apps.companies.models import Company, Feature

MORNING = 8


def watch_upkeep() -> int:
    sent = 0
    for company in Company.objects.filter(features__contains=[Feature.ASSETS], is_active=True):
        now = timezone.localtime(timezone.now(), posting.zone_of(company))
        if now.hour < MORNING:
            continue
        sent += company_upkeep(company, now.date())
    return sent


def company_upkeep(company, today) -> int:
    settings = conf.get_settings(company)
    ahead = today + timedelta(days=settings.remind_days)
    week = today + timedelta(days=7)
    sent = 0
    assets = (
        Asset.objects.for_company(company)
        .exclude(status=Asset.Status.DISPOSED)
        .select_related("company", "branch", "responsible")
    )
    for asset in assets:
        for what, day, soon in (
            ("warranty", asset.warranty_until, ahead),
            ("service", asset.next_service_on, week),
            ("verification", asset.next_verification_on, ahead),
            ("insurance", asset.insurance_until, ahead),
        ):
            if day is None or (asset.status == Asset.Status.SUSPENDED and what == "service"):
                continue
            if what in ("warranty", "insurance") and day < today:
                continue  # over: nothing left to do about it
            if day <= today:
                sent += notify.upkeep(asset, what, day, "due")
            elif day <= soon:
                sent += notify.upkeep(asset, what, day, "soon")
    permits = Permit.objects.for_company(company).filter(valid_until__isnull=False)
    for permit in permits.select_related("company", "branch", "responsible"):
        left = (permit.valid_until - today).days
        if left < 0 and left >= -30:
            sent += notify.permit(permit, "expired", today)
        elif 0 <= left <= 7:
            sent += notify.permit(permit, "week", today)
        elif left <= permit.remind_days:
            sent += notify.permit(permit, "soon", today)
    return sent
