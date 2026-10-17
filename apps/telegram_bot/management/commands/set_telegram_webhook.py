"""Management command to register the Telegram webhook (Section 5.3 & Patch B.4)."""
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.services.models import SiteConfig
from apps.telegram_bot.client import TelegramClient, TelegramError


class Command(BaseCommand):
    help = "Sets the Telegram webhook URL and registers the secret verification token."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            default="",
            help="Base site URL override (defaults to settings.SITE_URL)",
        )

    def handle(self, *args, **options):
        config = SiteConfig.get()
        token = config.get_tg_bot_token()

        if not token:
            raise CommandError("Telegram bot token is not configured in SiteConfig or settings.")

        secret = config.get_tg_webhook_secret()
        if not secret:
            secret = secrets.token_urlsafe(32)
            config.tg_webhook_secret_enc = config.set_tg_bot_token.__globals__["encrypt_secret"](secret)
            config.save(update_fields=["tg_webhook_secret_enc"])

        base_url = options["url"] or getattr(settings, "SITE_URL", "http://localhost:8000")
        webhook_url = f"{base_url.rstrip('/')}/telegram/webhook/"

        try:
            client = TelegramClient(token=token)
            me = client.get_me()
            username = me.get("username", "")
            if username and config.tg_bot_username != username:
                config.tg_bot_username = username
                config.save(update_fields=["tg_bot_username"])

            client.set_webhook(webhook_url=webhook_url, secret_token=secret)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully configured Telegram webhook for @{username} -> {webhook_url}"
                )
            )
        except TelegramError as exc:
            raise CommandError(f"Failed to set Telegram webhook: {exc}") from exc
