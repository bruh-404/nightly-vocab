"""Management command to evaluate and dispatch scheduled backups to Admin Telegram PM."""
from datetime import timedelta
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.services.models import SiteConfig
from apps.services.backup_service import send_system_backup_to_telegram

logger = logging.getLogger(__name__)

SCHEDULE_DELTAS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "three_days": timedelta(days=3),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

class Command(BaseCommand):
    help = "Dispatches scheduled database backup to Admin Telegram chat if due."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force immediate backup dispatch regardless of schedule interval.",
        )

    def handle(self, *args, **options):
        config = SiteConfig.get()
        if not config.backup_enabled and not options["force"]:
            self.stdout.write("Automated backups are currently disabled in SiteConfig.")
            return

        now = timezone.now()
        schedule_interval = SCHEDULE_DELTAS.get(config.backup_schedule, timedelta(days=1))

        if not options["force"] and config.backup_last_sent_at:
            elapsed = now - config.backup_last_sent_at
            if elapsed < schedule_interval:
                self.stdout.write(f"Backup not due yet (interval: {config.backup_schedule}, elapsed: {elapsed}).")
                return

        self.stdout.write("Generating and dispatching backup to Admin Telegram...")
        try:
            res = send_system_backup_to_telegram()
            self.stdout.write(self.style.SUCCESS(f"Backup sent successfully to Telegram: {res}"))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Failed to dispatch backup: {exc}"))
