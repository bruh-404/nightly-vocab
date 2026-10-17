"""Telegram Bot API client (Section 7.3 & Patch B.4)."""
import logging
from typing import Any, Dict, Optional

import httpx

from apps.services.models import SiteConfig

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    """Base exception for Telegram Bot API failures."""

    pass


class BotBlocked(TelegramError):
    """Raised when the Telegram user has blocked the bot (HTTP 403)."""

    pass


class BotNotConfigured(TelegramError):
    """Raised when Telegram bot token is missing or bot is globally disabled."""

    pass


class TelegramClient:
    """
    Thin, fully-mockable httpx client for Telegram Bot API operations.
    Handles token resolution, webhook registration, message delivery,
    and 403 BotBlocked detection.
    """

    def __init__(self, token: Optional[str] = None, timeout: float = 10.0):
        self.timeout = timeout
        if token:
            self.token = token.strip()
        else:
            config = SiteConfig.get()
            if not config.tg_enabled:
                raise BotNotConfigured("ربات تلگرام در تنظیمات سیستم غیرفعال است.")
            self.token = config.get_tg_bot_token()

        if not self.token:
            raise BotNotConfigured("توکن ربات تلگرام تنظیم نشده است.")

    def _url(self, method: str) -> str:
        return TELEGRAM_API_URL.format(token=self.token, method=method)

    def get_me(self) -> Dict[str, Any]:
        """Fetches basic bot information from Telegram to verify token."""
        url = self._url("getMe")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return data["result"]
            raise TelegramError(data.get("description", "Failed to verify bot token."))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Network error calling getMe: {exc}") from exc

    def set_webhook(self, webhook_url: str, secret_token: str) -> bool:
        """Sets the incoming webhook URL with secret token verification."""
        url = self._url("setWebhook")
        payload = {
            "url": webhook_url,
            "secret_token": secret_token,
            "drop_pending_updates": True,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return True
            raise TelegramError(data.get("description", "Failed to set webhook."))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Network error calling setWebhook: {exc}") from exc

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sends an HTML-formatted message to a user/chat.
        Classifies HTTP 403 as BotBlocked so caller can cleanly unlink.
        """
        url = self._url("sendMessage")
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)

            if resp.status_code == 403:
                raise BotBlocked(f"User {chat_id} has blocked the bot.")

            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return data["result"]

            raise TelegramError(data.get("description", "Failed to send message."))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Network error sending Telegram message: {exc}") from exc

    def send_document(
        self,
        chat_id: int | str,
        document_bytes: bytes,
        filename: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sends a file document directly to a user/chat via Telegram Bot API.
        """
        url = self._url("sendDocument")
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"

        files = {
            "document": (filename, document_bytes, "application/json"),
        }

        try:
            with httpx.Client(timeout=self.timeout + 20.0) as client:
                resp = client.post(url, data=data, files=files)

            if resp.status_code == 403:
                raise BotBlocked(f"User {chat_id} has blocked the bot.")

            res_json = resp.json()
            if resp.status_code == 200 and res_json.get("ok"):
                return res_json["result"]

            raise TelegramError(res_json.get("description", "Failed to send document."))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Network error sending Telegram document: {exc}") from exc

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> Dict[str, Any]:
        """
        Answers a callback query sent from an inline keyboard button click.
        """
        url = self._url("answerCallbackQuery")
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = show_alert

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return data["result"]
            raise TelegramError(data.get("description", "Failed to answer callback query."))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Network error answering callback query: {exc}") from exc

    def get_chat_member(self, chat_id: int | str, user_id: int | str) -> Dict[str, Any]:
        """
        Gets membership status of a user in a channel or group.
        """
        url = self._url("getChatMember")
        payload = {"chat_id": chat_id, "user_id": user_id}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return data["result"]
            raise TelegramError(data.get("description", "Failed to get chat member."))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Network error getting chat member: {exc}") from exc



