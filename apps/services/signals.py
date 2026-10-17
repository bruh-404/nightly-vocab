"""Signals for services app (Patch B)."""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserControl


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_control_on_user_create(sender, instance, created, **kwargs):
    """Automatically creates a UserControl record whenever a new user registers."""
    if created:
        UserControl.objects.get_or_create(user=instance)
