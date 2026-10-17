"""Data models for accounts app."""
import zoneinfo
from datetime import date, datetime, time
from typing import Any, List

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def validate_card_types(value: Any) -> None:
    """Validate that enabled_card_types is a non-empty subset of {1, 2, 3}."""
    if not isinstance(value, list) or not value:
        raise ValidationError("حداقل یک نوع کارت باید فعال باشد.")
    valid_types = {1, 2, 3}
    if not set(value).issubset(valid_types):
        raise ValidationError(f"انواع کارت نامعتبر است. مجاز: {valid_types}")

def default_card_types() -> List[int]:
    """Default active card types."""
    return [1, 2, 3]

class Profile(models.Model):
    """
    User profile in 1:1 relationship with auth.User.
    Stores learning configuration, SRS preferences, audio, and Telegram reminder settings.
    """
    DAILY_LIMIT_CHOICES = (
        (5, "5 کارت"),
        (10, "10 کارت"),
        (15, "15 کارت"),
        (20, "20 کارت"),
        (30, "30 کارت"),
    )

    ACCENT_CHOICES = (
        ("uk", "بریتانیایی (UK)"),
        ("us", "آمریکایی (US)"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    daily_limit = models.PositiveSmallIntegerField(
        choices=DAILY_LIMIT_CHOICES,
        default=20,
        help_text="حداکثر تعداد کارت‌های مروری و جدید در هر روز",
    )
    enabled_card_types = models.JSONField(
        default=default_card_types,
        validators=[validate_card_types],
        help_text="لیست انواع کارت‌های فعال [1, 2, 3]",
    )
    ai_example_enabled = models.BooleanField(
        default=False,
        help_text="تولید مثال اضافی توسط هوش مصنوعی",
    )
    accent = models.CharField(
        max_length=2,
        choices=ACCENT_CHOICES,
        default="uk",
        help_text="لهجه صوتی پیش‌فرض",
    )
    timezone = models.CharField(
        max_length=50,
        default="UTC",
        help_text="منطقه زمانی کاربر (IANA timezone)",
    )
    last_active_date = models.DateField(
        null=True,
        blank=True,
        help_text="تاریخ آخرین فعالیت مروری کاربر بر حسب منطقه زمانی محلی",
    )
    reminder_enabled = models.BooleanField(
        default=False,
        help_text="فعال‌بودن ارسال یادآوری در تلگرام",
    )
    reminder_time = models.TimeField(
        default=time(22, 0),
        help_text="ساعت یادآوری روزانه بر حسب منطقه زمانی کاربر",
    )
    telegram_chat_id = models.BigIntegerField(
        null=True,
        blank=True,
        unique=True,
        help_text="شناسه عددی چت در تلگرام",
    )
    telegram_link_token = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        help_text="توکن اتصال عمیق به ربات تلگرام",
    )
    last_reminder_sent_date = models.DateField(
        null=True,
        blank=True,
        help_text="تاریخ آخرین پیام یادآوری ارسالی",
    )
    deletion_requested_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="تاریخ و زمان ثبت درخواست حذف حساب کاربری (مهلت ۲۴ ساعته)",
    )
    password_login_enabled = models.BooleanField(
        default=False,
        help_text="آیا امکان ورود با رمز عبور علاوه بر گوگل فعال است؟",
    )

    def get_local_date(self) -> date:
        """Returns the user's current local date based on their timezone."""
        try:
            tz = zoneinfo.ZoneInfo(self.timezone)
        except Exception:
            tz = zoneinfo.ZoneInfo("UTC")
        return datetime.now(tz).date()

    def __str__(self) -> str:
        return f"Profile of {self.user.email or self.user.username}"
