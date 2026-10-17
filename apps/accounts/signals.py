"""Signals for accounts app."""
from typing import Any

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_save_user_profile(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Ensure a Profile exists whenever a User is created or saved."""
    if created:
        Profile.objects.create(user=instance)
    else:
        # If profile exists, save it; otherwise create it (defensive for existing users)
        if hasattr(instance, "profile"):
            instance.profile.save()
        else:
            Profile.objects.create(user=instance)


from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.utils import timezone


@receiver(user_logged_in)
def handle_user_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """If user logs in within the 24-hour grace period, cancel the pending deletion."""
    profile = getattr(user, "profile", None)
    if profile and profile.deletion_requested_at:
        now = timezone.now()
        if now - profile.deletion_requested_at <= timedelta(hours=24):
            profile.deletion_requested_at = None
            profile.save(update_fields=["deletion_requested_at"])
            if request:
                messages.success(request, "درخواست حذف حساب کاربری شما لغو شد و حساب شما با موفقیت حفظ گردید.")

