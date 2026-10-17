"""Management command to permanently purge accounts whose 24-hour deletion grace period has expired."""
from datetime import timedelta
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.accounts.models import Profile

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Permanently deletes user accounts whose 24-hour deletion grace period has elapsed."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=24)
        expired_profiles = Profile.objects.filter(
            deletion_requested_at__isnull=False,
            deletion_requested_at__lte=cutoff,
        ).select_related("user")

        purged_count = 0
        for p in expired_profiles:
            user = p.user
            user_desc = f"{user.email or user.username} (ID: {user.id})"
            self.stdout.write(f"Purging account: {user_desc} (requested at {p.deletion_requested_at})")
            user.delete()
            purged_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully purged {purged_count} expired account(s)."))
