"""Models for external services, AI usage tracking, site config, and access control (Patch B)."""
from django.conf import settings
from django.core.cache import cache
from django.db import models

from .crypto import decrypt_secret, encrypt_secret, mask_secret


class SiteConfig(models.Model):
    """
    Singleton site configuration (pk=1) storing shared API keys, bot tokens,
    global limits, and master switches (Patch B).
    """

    CACHE_KEY = "site_config_singleton"

    ai_provider = models.CharField(
        max_length=30,
        default="gemini",
        help_text="نام ارائه‌دهنده پیش‌فرض هوش مصنوعی",
    )
    ai_model = models.CharField(
        max_length=60,
        default="gemini-1.5-flash",
        help_text="مدل پیش‌فرض برای هوش مصنوعی",
    )
    shared_ai_key_enc = models.TextField(
        blank=True,
        default="",
        help_text="کلید رمزگذاری‌شده اشتراکی هوش مصنوعی",
    )
    shared_ai_key_last4 = models.CharField(
        max_length=4,
        blank=True,
        default="",
        help_text="چهار رقم آخر کلید اشتراکی جهت نمایش ماسک‌شده",
    )
    shared_ai_enabled = models.BooleanField(
        default=True,
        help_text="کلید اصلی قطع/وصل دسترسی به هوش مصنوعی اشتراکی",
    )

    # Telegram bot configuration
    tg_bot_token_enc = models.TextField(
        blank=True,
        default="",
        help_text="توکن رمزگذاری‌شده ربات تلگرام",
    )
    tg_bot_token_last4 = models.CharField(
        max_length=4,
        blank=True,
        default="",
    )
    tg_bot_username = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="نام کاربری تاییدشده ربات تلگرام",
    )
    tg_webhook_secret_enc = models.TextField(
        blank=True,
        default="",
        help_text="رمز هدر احراز هویت وب‌هوک تلگرام",
    )
    tg_enabled = models.BooleanField(
        default=True,
        help_text="کلید اصلی قطع/وصل فعالیت ربات تلگرام",
    )
    tg_rate_limit_type = models.CharField(
        max_length=10,
        choices=(
            ("daily", "روزانه"),
            ("hourly", "ساعتی"),
        ),
        default="daily",
        help_text="نوع بازه زمانی برای محدودیت تعداد پیام‌های دریافتی تلگرام",
    )
    tg_user_rate_limit = models.PositiveIntegerField(
        default=100,
        help_text="حداکثر تعداد پیام مجاز هر کاربر در بازه تعیین‌شده (0 = بدون محدودیت)",
    )
    tg_force_join_enabled = models.BooleanField(
        default=False,
        help_text="اجبار عضویت کاربر در کانال/گروه قبل از استفاده از ربات",
    )
    tg_force_join_targets = models.JSONField(
        default=list,
        blank=True,
        help_text="لیست کانال‌ها یا گروه‌های اجباری [{'channel': '...', 'title': '...', 'link': '...'}]",
    )
    tg_force_join_channel = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="آیدی کانال یا گروه (تک کانال - جهت سازگاری)",
    )
    tg_force_join_link = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="لینک جوین کانال یا گروه برای دکمه شیشه‌ای (اختیاری)",
    )

    # Google OAuth & Search Console Configuration
    google_client_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="شناسه Google OAuth Client ID",
    )
    google_client_secret_enc = models.TextField(
        blank=True,
        default="",
        help_text="کلید رمزگذاری‌شده Google OAuth Client Secret",
    )
    google_client_secret_last4 = models.CharField(
        max_length=4,
        blank=True,
        default="",
    )
    google_oauth_enabled = models.BooleanField(
        default=True,
        help_text="فعال بودن ورود با حساب کاربری گوگل",
    )
    google_site_verification = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="کد تایید مالکیت سایت در سرچ کنسول گوگل (Search Console)",
    )

    def get_force_join_channels(self) -> list:
        """Returns consolidated list of required channels/groups."""
        targets = []
        if isinstance(self.tg_force_join_targets, list):
            for t in self.tg_force_join_targets:
                if isinstance(t, dict) and t.get("channel"):
                    targets.append({
                        "channel": t.get("channel", "").strip(),
                        "title": t.get("title", "").strip() or t.get("channel", "").strip(),
                        "link": t.get("link", "").strip(),
                    })
        if not targets and self.tg_force_join_channel:
            targets.append({
                "channel": self.tg_force_join_channel.strip(),
                "title": self.tg_force_join_channel.strip(),
                "link": self.tg_force_join_link.strip(),
            })
        return targets

    # Default limits and access policies
    default_ai_access = models.CharField(
        max_length=15,
        choices=(
            ("shared", "استفاده از سهمیه اشتراکی"),
            ("own_only", "فقط کلید شخصی"),
            ("disabled", "غیرفعال"),
        ),
        default="shared",
    )
    default_ai_daily_limit = models.PositiveIntegerField(
        default=30,
        help_text="سقف روزانه درخواست کاربر به ازای کلید اشتراکی",
    )
    default_ai_monthly_limit = models.PositiveIntegerField(
        default=300,
        help_text="سقف ماهانه درخواست کاربر به ازای کلید اشتراکی",
    )
    default_max_targets_per_call = models.PositiveIntegerField(
        default=30,
        help_text="حداکثر تعداد کلمات در هر درخواست تحلیل",
    )
    global_ai_daily_cap = models.PositiveIntegerField(
        default=0,
        help_text="سقف روزانه کل فراخوانی‌های کلید اشتراکی (0 = نامحدود)",
    )
    global_ai_monthly_cap = models.PositiveIntegerField(
        default=0,
        help_text="سقف ماهانه کل فراخوانی‌های کلید اشتراکی (0 = نامحدود)",
    )
    default_telegram_access = models.CharField(
        max_length=15,
        choices=(
            ("allowed", "مجاز"),
            ("blocked", "مسدود"),
        ),
        default="allowed",
    )
    signups_open = models.BooleanField(
        default=True,
        help_text="آیا ثبت‌نام کاربران جدید باز است؟",
    )
    allowed_emails = models.TextField(
        blank=True,
        default="",
        help_text="لیست ایمیل‌های مجاز (هر سطر یک ایمیل)",
    )

    # Backup Configuration
    backup_enabled = models.BooleanField(
        default=False,
        help_text="فعال بودن ارسال خودکار بکاپ به پیوی ادمین در تلگرام",
    )
    backup_schedule = models.CharField(
        max_length=20,
        default="daily",
        choices=(
            ("hourly", "ساعتی (هر ۱ ساعت)"),
            ("daily", "روزانه (هر ۲۴ ساعت)"),
            ("three_days", "هر ۳ روز یک‌بار"),
            ("weekly", "هفتگی (هر ۷ روز)"),
            ("monthly", "ماهانه (هر ۳۰ روز)"),
        ),
        help_text="بازه زمانی ارسال خودکار بکاپ به تلگرام",
    )
    backup_telegram_chat_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="شناسه چت (Chat ID) تلگرام ادمین دریافت‌کننده بکاپ",
    )
    backup_last_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="تاریخ و زمان آخرین ارسال بکاپ",
    )

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def get(cls) -> "SiteConfig":
        """Returns cached singleton configuration or creates default."""
        config = cache.get(cls.CACHE_KEY)
        if config is None:
            config, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, config, 300)
        return config

    def set_shared_ai_key(self, raw_key: str) -> None:
        if raw_key:
            self.shared_ai_key_enc = encrypt_secret(raw_key.strip())
            self.shared_ai_key_last4 = raw_key.strip()[-4:]
        else:
            self.shared_ai_key_enc = ""
            self.shared_ai_key_last4 = ""

    def get_shared_ai_key(self) -> str:
        """Returns decrypted shared AI key, with fallback to settings.GEMINI_API_KEY."""
        if self.shared_ai_key_enc:
            decrypted = decrypt_secret(self.shared_ai_key_enc)
            if decrypted:
                return decrypted
        return getattr(settings, "GEMINI_API_KEY", "")

    def set_tg_bot_token(self, raw_token: str) -> None:
        if raw_token:
            self.tg_bot_token_enc = encrypt_secret(raw_token.strip())
            self.tg_bot_token_last4 = raw_token.strip()[-4:]
        else:
            self.tg_bot_token_enc = ""
            self.tg_bot_token_last4 = ""

    def get_tg_bot_token(self) -> str:
        """Returns decrypted bot token, with fallback to settings.TELEGRAM_BOT_TOKEN."""
        if self.tg_bot_token_enc:
            decrypted = decrypt_secret(self.tg_bot_token_enc)
            if decrypted:
                return decrypted
        return getattr(settings, "TELEGRAM_BOT_TOKEN", "")

    def get_tg_webhook_secret(self) -> str:
        """Returns decrypted webhook secret, with fallback to settings.TELEGRAM_WEBHOOK_SECRET."""
        if self.tg_webhook_secret_enc:
            decrypted = decrypt_secret(self.tg_webhook_secret_enc)
            if decrypted:
                return decrypted
        return getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")

    def set_google_client_secret(self, raw_secret: str) -> None:
        if raw_secret:
            self.google_client_secret_enc = encrypt_secret(raw_secret.strip())
            self.google_client_secret_last4 = raw_secret.strip()[-4:]
        else:
            self.google_client_secret_enc = ""
            self.google_client_secret_last4 = ""

    def get_google_client_secret(self) -> str:
        """Returns decrypted Google Client Secret, with fallback to settings.GOOGLE_CLIENT_SECRET."""
        if self.google_client_secret_enc:
            decrypted = decrypt_secret(self.google_client_secret_enc)
            if decrypted:
                return decrypted
        return getattr(settings, "GOOGLE_CLIENT_SECRET", "")

    def get_google_client_id(self) -> str:
        """Returns Google Client ID, with fallback to settings.GOOGLE_CLIENT_ID."""
        if self.google_client_id:
            return self.google_client_id
        return getattr(settings, "GOOGLE_CLIENT_ID", "")

    @property
    def has_google_oauth(self) -> bool:
        return bool(self.get_google_client_id() and self.get_google_client_secret())

    @property
    def masked_google_client_secret(self) -> str:
        if self.google_client_secret_last4:
            return f"••••••••{self.google_client_secret_last4}"
        sec = getattr(settings, "GOOGLE_CLIENT_SECRET", "")
        if sec:
            return f"••••••••{sec[-4:]}"
        return ""

    def sync_google_social_app(self) -> None:
        """Synchronizes Google OAuth credentials with django-allauth SocialApp and updates Site domain."""
        cid = self.get_google_client_id()
        sec = self.get_google_client_secret()
        if cid and sec:
            try:
                from allauth.socialaccount.models import SocialApp
                from django.contrib.sites.models import Site

                # Deduplicate any existing Google apps to prevent MultipleObjectsReturned
                existing = list(SocialApp.objects.filter(provider="google").order_by("id"))
                if existing:
                    app = existing[0]
                    for duplicate in existing[1:]:
                        duplicate.delete()
                else:
                    app = SocialApp(provider="google")

                app.name = "Google"
                app.client_id = cid
                app.secret = sec
                app.save()

                # Sync django.contrib.sites domain
                site = Site.objects.filter(pk=1).first()
                if site:
                    current_domain = getattr(settings, "DOMAIN", "")
                    if current_domain and (site.domain == "example.com" or site.domain != current_domain):
                        site.domain = current_domain
                        site.name = "Nightly Vocab"
                        site.save()
                    if site not in app.sites.all():
                        app.sites.add(site)
            except Exception:
                pass

    @property
    def ai_master_switch(self) -> bool:
        return self.shared_ai_enabled

    @ai_master_switch.setter
    def ai_master_switch(self, value: bool) -> None:
        self.shared_ai_enabled = bool(value)

    @property
    def has_shared_ai_key(self) -> bool:
        return bool(self.shared_ai_key_enc or getattr(settings, "GEMINI_API_KEY", ""))

    @property
    def masked_shared_ai_key(self) -> str:
        if self.shared_ai_key_last4:
            return f"••••{self.shared_ai_key_last4}"
        fallback = getattr(settings, "GEMINI_API_KEY", "")
        if fallback:
            return f"••••{fallback[-4:]}"
        return ""

    @property
    def has_tg_bot_token(self) -> bool:
        return bool(self.tg_bot_token_enc or getattr(settings, "TELEGRAM_BOT_TOKEN", ""))

    @property
    def masked_tg_bot_token(self) -> str:
        if self.tg_bot_token_last4:
            return f"••••{self.tg_bot_token_last4}"
        fallback = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if fallback:
            return f"••••{fallback[-4:]}"
        return ""

    def __str__(self) -> str:
        return "تنظیمات عمومی سامانه (SiteConfig)"



class UserControl(models.Model):
    """
    Per-user access controls and quotas set by administrators (Patch B).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="control",
    )
    ai_access = models.CharField(
        max_length=15,
        choices=(
            ("inherit", "ارث‌بری از تنظیمات پیش‌فرض"),
            ("shared", "مجاز به کلید اشتراکی"),
            ("own_only", "فقط با کلید شخصی"),
            ("disabled", "غیرفعال"),
        ),
        default="inherit",
    )
    ai_daily_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="سقف روزانه اختصاصی (خالی = ارث‌بری)",
    )
    ai_monthly_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="سقف ماهانه اختصاصی (خالی = ارث‌بری)",
    )
    max_targets_per_call = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="سقف اختصاصی تعداد کلمات در هر درخواست (خالی = ارث‌بری)",
    )
    telegram_access = models.CharField(
        max_length=15,
        choices=(
            ("inherit", "ارث‌بری از تنظیمات پیش‌فرض"),
            ("allowed", "مجاز"),
            ("blocked", "مسدود"),
        ),
        default="inherit",
    )
    is_blocked = models.BooleanField(
        default=False,
        help_text="مسدودسازی کامل کاربر از سامانه",
    )
    admin_note = models.TextField(
        blank=True,
        default="",
        help_text="یادداشت مدیر در رابطه با کاربر",
    )

    def __str__(self) -> str:
        return f"Control for {self.user.email or self.user.username}"


class UserApiKey(models.Model):
    """
    User-provided API key for Bring-Your-Own-Key (BYOK) flow (Patch B).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    provider = models.CharField(
        max_length=30,
        default="gemini",
    )
    key_enc = models.TextField(
        help_text="کلید رمزگذاری‌شده کاربر",
    )
    key_last4 = models.CharField(
        max_length=4,
    )
    enabled = models.BooleanField(
        default=True,
    )
    validated_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    last_error = models.TextField(
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider"],
                name="unique_user_provider_api_key",
            ),
        ]

    def set_key(self, raw_key: str) -> None:
        self.key_enc = encrypt_secret(raw_key.strip())
        self.key_last4 = raw_key.strip()[-4:]

    def get_key(self) -> str:
        return decrypt_secret(self.key_enc)

    def masked(self) -> str:
        return mask_secret(self.get_key())

    def __str__(self) -> str:
        return f"{self.provider} key for {self.user.email} (••••{self.key_last4})"


class AiUsage(models.Model):
    """
    Tracks daily AI API calls per user for quota enforcement and usage metrics.
    Supports both shared key and personal (own) key usage (Patch B).
    """

    SOURCE_CHOICES = (
        ("shared", "کلید سرور (Shared)"),
        ("own", "کلید شخصی (Own)"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_usages",
    )
    date = models.DateField(
        help_text="تاریخ محلی مصرف",
    )
    source = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default="shared",
        help_text="منبع کلید API استفاده‌شده",
    )
    calls = models.PositiveIntegerField(
        default=0,
        help_text="تعداد فراخوانی‌های موفق",
    )
    failed_calls = models.PositiveIntegerField(
        default=0,
        help_text="تعداد فراخوانی‌های ناموفق یا ردشده",
    )
    input_tokens = models.PositiveIntegerField(
        default=0,
        help_text="تعداد توکن‌های ورودی بر اساس متادیتای ارائه‌دهنده",
    )
    output_tokens = models.PositiveIntegerField(
        default=0,
        help_text="تعداد توکن‌های خروجی بر اساس متادیتای ارائه‌دهنده",
    )

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["user", "date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date", "source"],
                name="unique_user_date_source_ai_usage",
            ),
        ]

    def __str__(self) -> str:
        return f"AI Usage for {self.user.email or self.user.username} on {self.date} ({self.source}): {self.calls} calls"


class TelegramUsage(models.Model):
    """
    Tracks Telegram reminder messages sent per user per day (Patch B).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_usages",
    )
    date = models.DateField()
    messages_sent = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"],
                name="unique_user_date_telegram_usage",
            ),
        ]

    def __str__(self) -> str:
        return f"TG Usage for {self.user.email} on {self.date}: {self.messages_sent} sent"


class AdminAuditLog(models.Model):
    """
    Audit log for actions performed in the management panel (Patch B).
    Never stores secrets in details.
    """

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=60)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="target_audit_logs",
    )
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Audit: {self.action} by {self.admin} at {self.created_at}"
