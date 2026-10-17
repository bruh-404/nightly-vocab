"""Admin configuration for cards app."""
from django.contrib import admin

from .models import DailySession, ReviewLog, WordCard


@admin.register(WordCard)
class WordCardAdmin(admin.ModelAdmin):
    list_display = (
        "word",
        "user",
        "stage",
        "target_type",
        "interval_days",
        "next_review_date",
        "consecutive_wrong",
        "total_wrong",
        "is_suspended",
    )
    list_filter = ("stage", "target_type", "is_suspended", "next_review_date")
    search_fields = ("word", "lemma", "meaning", "user__email", "user__username")
    readonly_fields = ("created_at",)


@admin.register(ReviewLog)
class ReviewLogAdmin(admin.ModelAdmin):
    list_display = (
        "card",
        "user",
        "local_date",
        "display_type",
        "meaning_correct",
        "spelling_correct",
        "outcome",
        "reviewed_at",
    )
    list_filter = ("local_date", "display_type", "meaning_correct", "outcome")
    search_fields = ("card__word", "user__email", "typed_input")
    readonly_fields = ("reviewed_at",)


@admin.register(DailySession)
class DailySessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "local_date",
        "review_count",
        "new_count",
        "prev_active_date",
        "created_at",
    )
    list_filter = ("local_date",)
    search_fields = ("user__email", "user__username")
    readonly_fields = ("created_at",)
