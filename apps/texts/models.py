"""Models for texts app."""
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Text(models.Model):
    """
    Nightly English reading text entered by the user.
    Once any WordCard references this text, body becomes read-only to preserve character offsets.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="texts",
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="عنوان متن (در صورت خالی بودن خودکار پر می‌شود)",
    )
    body = models.TextField(
        max_length=10000,
        help_text="متن کامل انگلیسی (حداکثر ۱۰٬۰۰۰ نویسه)",
    )
    text_date = models.DateField(
        default=timezone.now,
        help_text="تاریخ محلی متن",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def clean(self) -> None:
        super().clean()
        # Enforce read-only body once cards exist
        if self.pk:
            original = Text.objects.filter(pk=self.pk).values("body").first()
            if original and original["body"] != self.body:
                if self.cards.exists():
                    raise ValidationError(
                        "متن اصلی دارای کلمات ذخیره‌شده است و نمی‌توان آن را ویرایش کرد (مختصات کلمات به هم می‌ریزد)."
                    )

    def save(self, *args, **kwargs) -> None:
        # Normalize newlines to \n
        if self.body:
            self.body = self.body.replace("\r\n", "\n").replace("\r", "\n")

        # Auto-title if blank
        if not self.title.strip():
            d = self.text_date if isinstance(self.text_date, date) else timezone.now().date()
            self.title = f"Text — {d.isoformat()}"

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title} ({self.user.email or self.user.username})"
