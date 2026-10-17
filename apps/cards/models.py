"""Models for cards, reviews, and daily sessions."""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.texts.models import Text


def default_list() -> list:
    return []


class WordCard(models.Model):
    """
    Word / phrase flashcard containing learning content and SRS memory progression state.
    """

    POS_CHOICES = (
        ("noun", "Noun"),
        ("verb", "Verb"),
        ("adjective", "Adjective"),
        ("adverb", "Adverb"),
        ("preposition", "Preposition"),
        ("conjunction", "Conjunction"),
        ("pronoun", "Pronoun"),
        ("determiner", "Determiner"),
        ("interjection", "Interjection"),
        ("phrasal verb", "Phrasal Verb"),
        ("idiom", "Idiom"),
        ("phrase", "Phrase"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cards",
        db_index=True,
    )
    source_text = models.ForeignKey(
        Text,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cards",
        help_text="متن اصلی که واژه از آن استخراج شده است",
    )
    word = models.CharField(
        max_length=120,
        help_text="واژه یا عبارت مشخص‌شده توسط کاربر در متن",
    )
    lemma = models.CharField(
        max_length=120,
        blank=True,
        help_text="شکل پایه واژه در دیکشنری (پیشنهاد هوش مصنوعی)",
    )
    pos = models.CharField(
        max_length=20,
        choices=POS_CHOICES,
        blank=True,
        help_text="نقش دستوری واژه در این بستر متنی",
    )
    meaning = models.TextField(
        blank=True,
        help_text="معنی فارسی در این بستر متنی (در صورت عدم اطمینان خالی می‌ماند)",
    )
    context_sentence = models.TextField(
        help_text="جمله استخراج‌شده از متن اصلی حاوی واژه",
    )
    ctx_start = models.PositiveIntegerField(
        help_text="اندیس شروع واژه در context_sentence",
    )
    ctx_end = models.PositiveIntegerField(
        help_text="اندیس پایان واژه در context_sentence",
    )
    char_start = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="اندیس شروع واژه در Text.body برای هایلایت علامت تعجب",
    )
    char_end = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="اندیس پایان واژه در Text.body برای هایلایت علامت تعجب",
    )
    ai_example = models.TextField(
        blank=True,
        help_text="مثال مکمل اختیاری تولیدشده با هوش مصنوعی",
    )
    audio_url_uk = models.URLField(
        blank=True,
        help_text="آدرس فایل صوتی تلفظ انسان (لهجه UK)",
    )
    audio_url_us = models.URLField(
        blank=True,
        help_text="آدرس فایل صوتی تلفظ انسان (لهجه US)",
    )
    audio_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="تاریخ آخرین استعلام فایل صوتی",
    )

    # SRS progression parameters (maps 1:1 to CardState in apps.srs.engine)
    stage = models.SmallIntegerField(
        default=0,
        help_text="مرحله حافظه از ۰ (جدید) تا ۸ (تثبیت دائم ۳ ماهه)",
    )
    target_type = models.SmallIntegerField(
        default=1,
        help_text="نوع آزمون ذاتی کارت (۱: معنی، ۲: هدایت‌شده، ۳: دیکته کامل)",
    )
    interval_days = models.IntegerField(
        default=0,
        help_text="فاصله زمانی آخرین مرور به روز",
    )
    next_review_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="تاریخ مرور بعدی در منطقه زمانی کاربر",
    )
    last_reviewed_date = models.DateField(
        null=True,
        blank=True,
        help_text="تاریخ آخرین مرور ثبت‌شده",
    )
    consecutive_wrong = models.IntegerField(
        default=0,
        help_text="تعداد دفعات متوالی عدم یادآوری معنی",
    )
    total_wrong = models.IntegerField(
        default=0,
        help_text="مجموع کل خطاهای معنی یا املا در طول عمر کارت",
    )
    weak_indices = models.JSONField(
        default=default_list,
        help_text="لیست اندیس‌های کاراکترهای اشتباه تایپ‌شده در آخرین آزمون املا",
    )
    is_suspended = models.BooleanField(
        default=False,
        help_text="معلق بودن کارت (خارج شدن از صف‌های مرور و کلمات جدید)",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["user", "stage", "next_review_date"]),
            models.Index(fields=["user", "is_suspended"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(stage__gte=0, stage__lte=8),
                name="valid_stage_range",
            ),
            models.CheckConstraint(
                condition=Q(target_type__gte=1, target_type__lte=3),
                name="valid_target_type_range",
            ),
            models.UniqueConstraint(
                fields=["user", "source_text", "char_start", "char_end"],
                condition=Q(char_start__isnull=False),
                name="unique_text_span_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.word} (Stage {self.stage}, {self.user.email or self.user.username})"


class ReviewLog(models.Model):
    """
    Append-only log of every flashcard review.
    Enforces idempotency (max 1 review per card per local day).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_logs",
    )
    card = models.ForeignKey(
        WordCard,
        on_delete=models.CASCADE,
        related_name="review_logs",
    )
    reviewed_at = models.DateTimeField(
        auto_now_add=True,
    )
    local_date = models.DateField(
        help_text="تاریخ محلی کاربر در زمان مرور",
    )
    display_type = models.SmallIntegerField(
        help_text="نوع نمایش داده‌شده در آزمون (۱ تا ۳)",
    )
    meaning_correct = models.BooleanField(
        help_text="آیا معنی کلمه را بلد بود؟",
    )
    spelling_correct = models.BooleanField(
        null=True,
        blank=True,
        help_text="آیا املای کلمه درست بود؟ (برای نوع ۲ و ۳)",
    )
    typed_input = models.CharField(
        max_length=255,
        blank=True,
        help_text="متن تایپ‌شده توسط کاربر",
    )
    stage_before = models.SmallIntegerField()
    stage_after = models.SmallIntegerField()
    target_type_before = models.SmallIntegerField()
    target_type_after = models.SmallIntegerField()
    interval_after = models.IntegerField()
    outcome = models.SmallIntegerField(
        help_text="کد برآمد آزمون (۱ تا ۴)",
    )

    class Meta:
        ordering = ["-reviewed_at"]
        indexes = [
            models.Index(fields=["user", "local_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["card", "local_date"],
                name="unique_review_per_card_per_day",
            ),
        ]

    def __str__(self) -> str:
        return f"Review #{self.id} for {self.card.word} on {self.local_date}"


class DailySession(models.Model):
    """
    Snapshot of the daily review queue to ensure browser refreshes do not shift the queue.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_sessions",
    )
    local_date = models.DateField(
        help_text="تاریخ محلی کاربر برای این جلسه",
    )
    card_ids = models.JSONField(
        default=default_list,
        help_text="لیست مرتب‌شده شناسه‌های کارت‌ها برای مرور امروز",
    )
    prev_active_date = models.DateField(
        null=True,
        blank=True,
        help_text="عکس لحظه‌ای از آخرین تاریخ فعالیت کاربر قبل از مرور امروز",
    )
    review_count = models.PositiveIntegerField(
        default=0,
        help_text="تعداد کارت‌های موعد مرور انتخاب‌شده",
    )
    new_count = models.PositiveIntegerField(
        default=0,
        help_text="تعداد کلمات جدید تزریق‌شده",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-local_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "local_date"],
                name="unique_daily_session_per_user_per_date",
            ),
        ]

    def __str__(self) -> str:
        return f"DailySession for {self.user.email or self.user.username} on {self.local_date}"
