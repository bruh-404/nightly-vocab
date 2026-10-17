"""Usage monitoring and rate-limit query helpers for AI services."""
from datetime import date
from typing import Dict, Optional

from django.contrib.auth.models import User
from django.db.models import Sum

from apps.services.models import AiUsage, SiteConfig, UserApiKey, UserControl


def get_user_ai_usage_summary(user: User, local_date: Optional[date] = None) -> Dict[str, any]:
    """
    Returns today's and this month's AI usage and limits for the user.
    Used in dashboard, settings, and UI banners.
    """
    if local_date is None:
        local_date = date.today()

    config = SiteConfig.get()
    control, _ = UserControl.objects.get_or_create(user=user)

    has_own_key = UserApiKey.objects.filter(
        user=user, provider=config.ai_provider, enabled=True
    ).exists()

    month_start = local_date.replace(day=1)

    # Today's shared usage
    today_shared = AiUsage.objects.filter(
        user=user, date=local_date, source="shared"
    ).aggregate(sum=Sum("calls"))["sum"] or 0

    # Month's shared usage
    month_shared = AiUsage.objects.filter(
        user=user, date__gte=month_start, date__lte=local_date, source="shared"
    ).aggregate(sum=Sum("calls"))["sum"] or 0

    # Own usage today and this month
    today_own = AiUsage.objects.filter(
        user=user, date=local_date, source="own"
    ).aggregate(sum=Sum("calls"))["sum"] or 0
    month_own = AiUsage.objects.filter(
        user=user, date__gte=month_start, date__lte=local_date, source="own"
    ).aggregate(sum=Sum("calls"))["sum"] or 0

    daily_limit = (
        control.ai_daily_limit
        if control.ai_daily_limit is not None
        else config.default_ai_daily_limit
    )
    monthly_limit = (
        control.ai_monthly_limit
        if control.ai_monthly_limit is not None
        else config.default_ai_monthly_limit
    )

    return {
        "has_own_key": has_own_key,
        "is_blocked": control.is_blocked,
        "ai_access": control.ai_access,
        "today_shared": today_shared,
        "month_shared": month_shared,
        "today_own": today_own,
        "month_own": month_own,
        "daily_limit": daily_limit,
        "monthly_limit": monthly_limit,
        "daily_remaining": max(0, daily_limit - today_shared),
    }
