"""Management command to dispatch scheduled Telegram review reminders (Section 5.3 & Patch B.4)."""
import logging
import zoneinfo
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Profile
from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.services.models import SiteConfig, TelegramUsage, UserControl
from apps.telegram_bot.client import BotBlocked, BotNotConfigured, TelegramClient, TelegramError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Dispatches daily Telegram review reminders within the user-configured time window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Forces sending reminders ignoring time-window checks (useful for testing).",
        )

    def handle(self, *args, **options):
        config = SiteConfig.get()
        if not config.tg_enabled:
            self.stdout.write("Telegram bot is globally disabled in SiteConfig. Skipping reminders.")
            return

        try:
            client = TelegramClient()
        except BotNotConfigured as exc:
            self.stdout.write(f"Telegram client not configured: {exc}. Skipping.")
            return

        site_url = getattr(settings, "SITE_URL", "http://localhost:8000")
        force = options["force"]
        sent_count = 0
        blocked_count = 0
        skipped_count = 0

        # Query candidates: reminder enabled and chat_id present
        candidate_ids = list(
            Profile.objects.filter(
                reminder_enabled=True,
                telegram_chat_id__isnull=False,
            ).values_list("id", flat=True)
        )

        for profile_id in candidate_ids:
            with transaction.atomic():
                profile = (
                    Profile.objects.select_for_update(skip_locked=True)
                    .filter(pk=profile_id)
                    .first()
                )
                if not profile:
                    continue

                try:
                    tz = zoneinfo.ZoneInfo(profile.timezone)
                except Exception:
                    tz = zoneinfo.ZoneInfo("UTC")

                local_now = datetime.now(tz)
                local_today = local_now.date()

                # 1. Skip if already sent today
                if profile.last_reminder_sent_date == local_today and not force:
                    skipped_count += 1
                    continue

                # 2. Time-window check: local_now >= reminder_time and within 3 hours
                if not force:
                    reminder_dt = datetime.combine(local_today, profile.reminder_time, tzinfo=tz)
                    if local_now < reminder_dt:
                        skipped_count += 1
                        continue
                    if local_now > reminder_dt + timedelta(hours=3):
                        skipped_count += 1
                        continue

                # 3. Access control check (Patch B.4)
                control = UserControl.objects.filter(user=profile.user).first()
                if control and (control.is_blocked or control.telegram_access == "blocked"):
                    skipped_count += 1
                    continue

                # 4. Check whether user has cards remaining to study today
                due_count = WordCard.objects.filter(
                    user=profile.user,
                    is_suspended=False,
                    stage__gt=0,
                    next_review_date__lte=local_today,
                ).count()

                new_count = WordCard.objects.filter(
                    user=profile.user,
                    is_suspended=False,
                    stage=0,
                ).count()

                reviewed_today = ReviewLog.objects.filter(
                    user=profile.user,
                    local_date=local_today,
                ).count()

                session = DailySession.objects.filter(
                    user=profile.user,
                    local_date=local_today,
                ).first()

                session_total = (
                    len(session.card_ids)
                    if session
                    else min(profile.daily_limit, due_count + new_count)
                )

                if session_total == 0 or reviewed_today >= session_total:
                    # Nothing to study or session already finished
                    skipped_count += 1
                    continue

                remaining = session_total - reviewed_today
                if remaining <= 0:
                    skipped_count += 1
                    continue

                # Prepare reminder message
                text = (
                    f"🌙 <b>وقت مرور شبانه‌ست!</b>\n\n"
                    f"امروز <b>{remaining}</b> کارت منتظر شماست تا زنجیره یادگیری‌تان حفظ شود."
                )
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {
                                "text": "شروع مرور امشب 🌙",
                                "url": f"{site_url.rstrip('/')}/review/",
                            }
                        ]
                    ]
                }

                # Attempt delivery
                try:
                    client.send_message(
                        chat_id=profile.telegram_chat_id,
                        text=text,
                        reply_markup=reply_markup,
                    )
                    profile.last_reminder_sent_date = local_today
                    profile.save(update_fields=["last_reminder_sent_date"])

                    # Track usage
                    usage, _ = TelegramUsage.objects.get_or_create(
                        user=profile.user,
                        date=local_today,
                    )
                    usage.messages_sent += 1
                    usage.save(update_fields=["messages_sent"])

                    sent_count += 1
                except BotBlocked:
                    logger.info("User %s blocked the bot. Disabling reminders.", profile.user.email)
                    profile.telegram_chat_id = None
                    profile.reminder_enabled = False
                    profile.save(update_fields=["telegram_chat_id", "reminder_enabled"])
                    blocked_count += 1
                except TelegramError as exc:
                    logger.warning("Failed to deliver reminder to user %s: %s", profile.user.email, exc)

        self.stdout.write(
            self.style.SUCCESS(
                f"Reminder dispatch finished: {sent_count} sent, {blocked_count} blocked/unlinked, {skipped_count} skipped."
            )
        )
