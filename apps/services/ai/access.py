"""Access resolution, quota checking, and atomic reservation for AI services (Patch B.3)."""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Sum

from apps.services.models import AiUsage, SiteConfig, UserApiKey, UserControl


@dataclass(frozen=True)
class Resolution:
    """Resolved AI access configuration for a user request."""

    source: str  # 'own' or 'shared'
    api_key: str
    model: str
    daily_limit: int
    monthly_limit: int
    max_targets: int


class AiDenied(Exception):
    """Raised when an AI request is denied due to quota or access policy."""

    MESSAGES = {
        "blocked": "حساب کاربری شما مسدود شده است.",
        "disabled": "دسترسی هوش مصنوعی برای حساب تو غیرفعال شده است.",
        "own_key_required": "برای استفاده از هوش مصنوعی باید در تنظیمات کلید API خودت را وارد کنی.",
        "shared_unavailable": "سرویس هوش مصنوعی مشترک در حال حاضر در دسترس نیست.",
        "global_cap": "ظرفیت هوش مصنوعی مشترک موقتاً تمام شده است.",
        "user_limit_daily": "سهمیهٔ امروزِ هوش مصنوعی تمام شد. فردا دوباره امتحان کن یا در تنظیمات کلید API شخصی‌ات را وارد کن.",
        "user_limit_monthly": "سهمیهٔ ماهانهٔ هوش مصنوعی اشتراکی شما به پایان رسیده است.",
        "too_many_targets": "تعداد کلمات انتخاب‌شده بیش از سقف مجاز است.",
    }

    def __init__(self, reason: str):
        self.reason = reason
        self.user_message = self.MESSAGES.get(
            reason, "امکان استفاده از هوش مصنوعی در حال حاضر مقدور نیست."
        )
        super().__init__(self.user_message)


def resolve_ai_source(user: User, num_targets: int = 1, local_date: Optional[date] = None) -> Resolution:
    """
    Evaluates permissions and limits in strict priority order (Patch B.3).
    Returns Resolution or raises AiDenied.
    """
    if local_date is None:
        local_date = date.today()

    config = SiteConfig.get()
    control, _ = UserControl.objects.get_or_create(user=user)

    # 1. Blocked user check
    if control.is_blocked:
        raise AiDenied("blocked")

    # 2. Check for personal Bring-Your-Own-Key (BYOK)
    own_key_obj = UserApiKey.objects.filter(user=user, provider=config.ai_provider, enabled=True).first()
    if own_key_obj:
        raw_key = own_key_obj.get_key()
        if raw_key:
            return Resolution(
                source="own",
                api_key=raw_key,
                model=config.ai_model,
                daily_limit=9999,
                monthly_limit=99999,
                max_targets=control.max_targets_per_call or config.default_max_targets_per_call,
            )

    # 3. Effective access on shared key
    effective_access = control.ai_access
    if effective_access == "inherit":
        effective_access = config.default_ai_access

    if effective_access == "disabled":
        raise AiDenied("disabled")
    if effective_access == "own_only":
        raise AiDenied("own_key_required")

    # 4. Shared key availability
    if not config.shared_ai_enabled:
        raise AiDenied("shared_unavailable")

    shared_key = config.get_shared_ai_key()
    if not shared_key:
        raise AiDenied("shared_unavailable")

    # 5. Global caps check (0 = unlimited)
    if config.global_ai_daily_cap > 0:
        total_today = AiUsage.objects.filter(
            date=local_date, source="shared"
        ).aggregate(sum=Sum("calls"))["sum"] or 0
        if total_today >= config.global_ai_daily_cap:
            raise AiDenied("global_cap")

    if config.global_ai_monthly_cap > 0:
        month_start = local_date.replace(day=1)
        total_month = AiUsage.objects.filter(
            date__gte=month_start, date__lte=local_date, source="shared"
        ).aggregate(sum=Sum("calls"))["sum"] or 0
        if total_month >= config.global_ai_monthly_cap:
            raise AiDenied("global_cap")

    # 6. User daily & monthly limits
    effective_daily_limit = (
        control.ai_daily_limit
        if control.ai_daily_limit is not None
        else config.default_ai_daily_limit
    )
    effective_monthly_limit = (
        control.ai_monthly_limit
        if control.ai_monthly_limit is not None
        else config.default_ai_monthly_limit
    )

    user_today_usage = AiUsage.objects.filter(
        user=user, date=local_date, source="shared"
    ).first()
    today_calls = user_today_usage.calls if user_today_usage else 0

    if today_calls >= effective_daily_limit:
        raise AiDenied("user_limit_daily")

    month_start = local_date.replace(day=1)
    user_month_calls = AiUsage.objects.filter(
        user=user, date__gte=month_start, date__lte=local_date, source="shared"
    ).aggregate(sum=Sum("calls"))["sum"] or 0

    if user_month_calls >= effective_monthly_limit:
        raise AiDenied("user_limit_monthly")

    # 7. Targets limit
    max_targets = (
        control.max_targets_per_call
        if control.max_targets_per_call is not None
        else config.default_max_targets_per_call
    )
    if num_targets > max_targets:
        raise AiDenied("too_many_targets")

    return Resolution(
        source="shared",
        api_key=shared_key,
        model=config.ai_model,
        daily_limit=effective_daily_limit,
        monthly_limit=effective_monthly_limit,
        max_targets=max_targets,
    )


@transaction.atomic
def reserve_ai_call(user: User, source: str, today: date, max_limit: int) -> AiUsage:
    """
    Atomically reserves a call by locking the AiUsage row and incrementing calls.
    Prevents race condition / concurrency overages.
    """
    usage, _ = AiUsage.objects.select_for_update().get_or_create(
        user=user,
        date=today,
        source=source,
        defaults={"calls": 0, "failed_calls": 0},
    )

    # Check limit again under lock for shared calls
    if source == "shared" and usage.calls >= max_limit:
        raise AiDenied("user_limit_daily")

    usage.calls += 1
    usage.save(update_fields=["calls"])
    return usage


@transaction.atomic
def release_ai_reservation_on_failure(usage_id: int) -> None:
    """
    Releases reservation if external AI call failed with a server/network error.
    Decrements calls and increments failed_calls.
    """
    usage = AiUsage.objects.select_for_update().filter(pk=usage_id).first()
    if usage and usage.calls > 0:
        usage.calls -= 1
        usage.failed_calls += 1
        usage.save(update_fields=["calls", "failed_calls"])


def record_ai_tokens(usage_id: int, input_tokens: int, output_tokens: int) -> None:
    """Records token consumption metrics in the usage row."""
    if input_tokens > 0 or output_tokens > 0:
        AiUsage.objects.filter(pk=usage_id).update(
            input_tokens=F("input_tokens") + input_tokens,
            output_tokens=F("output_tokens") + output_tokens,
        )
