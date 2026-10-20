"""Comprehensive backup and restore service for LexiContext / Nightly Vocab."""
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile
from apps.cards.models import WordCard
from apps.services.models import SiteConfig
from apps.telegram_bot.client import TelegramClient, TelegramError
from apps.texts.models import Text

logger = logging.getLogger(__name__)
User = get_user_model()


# =====================================================================
# 1. System-Wide Full Backup (Admin / Telegram)
# =====================================================================

def generate_system_backup_dict() -> Dict[str, Any]:
    """Generates a complete snapshot of all users, configs, texts, and flashcards."""
    config = SiteConfig.get()

    site_config_data = {
        "ai_provider": config.ai_provider,
        "ai_model": config.ai_model,
        "shared_ai_enabled": config.shared_ai_enabled,
        "tg_enabled": config.tg_enabled,
        "tg_bot_username": config.tg_bot_username,
        "default_ai_access": config.default_ai_access,
        "default_ai_daily_limit": config.default_ai_daily_limit,
        "default_ai_monthly_limit": config.default_ai_monthly_limit,
        "default_max_targets_per_call": config.default_max_targets_per_call,
        "global_ai_daily_cap": config.global_ai_daily_cap,
        "global_ai_monthly_cap": config.global_ai_monthly_cap,
        "default_telegram_access": config.default_telegram_access,
        "signups_open": config.signups_open,
        "allowed_emails": config.allowed_emails,
        "backup_enabled": config.backup_enabled,
        "backup_schedule": config.backup_schedule,
        "backup_telegram_chat_id": config.backup_telegram_chat_id,
    }

    users_data = []
    for u in User.objects.all().select_related("profile"):
        prof = getattr(u, "profile", None)
        u_item = {
            "username": u.username,
            "email": u.email,
            "is_staff": u.is_staff,
            "is_superuser": u.is_superuser,
            "date_joined": u.date_joined.isoformat(),
            "profile": {
                "daily_limit": prof.daily_limit if prof else 20,
                "accent": prof.accent if prof else "us",
                "timezone": prof.timezone if prof else "Asia/Tehran",
                "ai_example_enabled": prof.ai_example_enabled if prof else False,
                "reminder_enabled": prof.reminder_enabled if prof else False,
                "reminder_time": prof.reminder_time.strftime("%H:%M") if prof and prof.reminder_time else "22:00",
                "telegram_chat_id": prof.telegram_chat_id if prof else None,
            } if prof else None,
        }
        users_data.append(u_item)

    texts_data = []
    for t in Text.objects.all().select_related("user"):
        texts_data.append({
            "user_email": t.user.email or t.user.username,
            "title": t.title,
            "body": t.body,
            "created_at": t.created_at.isoformat(),
        })

    cards_data = []
    for c in WordCard.objects.all().select_related("user", "source_text"):
        cards_data.append({
            "user_email": c.user.email or c.user.username,
            "source_text_title": c.source_text.title if c.source_text else None,
            "word": c.word,
            "lemma": c.lemma,
            "pos": c.pos,
            "meaning": c.meaning,
            "context_sentence": c.context_sentence,
            "ctx_start": c.ctx_start,
            "ctx_end": c.ctx_end,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "ai_example": c.ai_example,
            "audio_url_uk": c.audio_url_uk,
            "audio_url_us": c.audio_url_us,
            "stage": c.stage,
            "target_type": c.target_type,
            "interval_days": c.interval_days,
            "next_review_date": c.next_review_date.isoformat() if c.next_review_date else None,
            "last_reviewed_date": c.last_reviewed_date.isoformat() if c.last_reviewed_date else None,
            "consecutive_wrong": c.consecutive_wrong,
            "weak_indices": c.weak_indices,
            "is_suspended": c.is_suspended,
        })

    return {
        "export_type": "nightly_vocab_system_full_backup",
        "version": "1.0",
        "created_at": timezone.now().isoformat(),
        "site_config": site_config_data,
        "users": users_data,
        "texts": texts_data,
        "cards": cards_data,
    }


def generate_system_backup_bytes() -> bytes:
    """Serializes system backup directly into UTF-8 JSON bytes in memory."""
    data = generate_system_backup_dict()
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def send_system_backup_to_telegram(target_chat_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Generates backup in memory and sends it directly to admin's private Telegram chat.
    Does NOT save files permanently to disk.
    """
    config = SiteConfig.get()
    chat_id = target_chat_id or config.backup_telegram_chat_id

    if not chat_id:
        # Fallback to first superuser with connected telegram
        admin_prof = Profile.objects.filter(
            user__is_superuser=True,
            telegram_chat_id__isnull=False,
        ).first()
        if admin_prof:
            chat_id = admin_prof.telegram_chat_id

    if not chat_id:
        raise ValueError("شناسه چت تلگرام ادمین (Chat ID) یافت نشد. لطفاً در تنظیمات ربات ثبت کنید.")

    backup_bytes = generate_system_backup_bytes()
    now_str = timezone.now().strftime("%Y-%m-%d_%H%M")
    filename = f"lexicontext_backup_{now_str}.json"
    caption = (
        f"📦 <b>نسخه پشتیبان سامانه Nightly Vocab</b>\n\n"
        f"🗓 تاریخ تولید: <code>{now_str}</code>\n"
        f"💾 حجم فایل: <code>{len(backup_bytes) / 1024:.1f} KB</code>\n\n"
        f"جهت بازیابی، کافیست این فایل را در بخش مدیریت بارگذاری نمایید."
    )

    client = TelegramClient()
    result = client.send_document(
        chat_id=chat_id,
        document_bytes=backup_bytes,
        filename=filename,
        caption=caption,
    )

    config.backup_last_sent_at = timezone.now()
    config.save(update_fields=["backup_last_sent_at"])
    return result


def restore_system_backup(data: Dict[str, Any]) -> Dict[str, int]:
    """
    Restores the complete database state from the uploaded JSON backup.
    Runs atomically.
    """
    if data.get("export_type") not in ("nightly_vocab_system_full_backup", "lexicontext_system_full_backup"):
        raise ValueError("قالب فایل پشتیبان نامعتبر است (نوع فایل پشتیبان سیستم نیست).")

    stats = {"users": 0, "texts": 0, "cards": 0}

    with transaction.atomic():
        # 1. Restore SiteConfig if present
        cfg_data = data.get("site_config", {})
        if cfg_data:
            config = SiteConfig.get()
            for key, val in cfg_data.items():
                if hasattr(config, key):
                    setattr(config, key, val)
            config.save()

        # 2. Restore Users & Profiles
        users_by_identifier = {}
        for u_info in data.get("users", []):
            username = u_info["username"]
            email = u_info.get("email", "")
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "is_staff": u_info.get("is_staff", False),
                    "is_superuser": u_info.get("is_superuser", False),
                },
            )
            if not created and email:
                user.email = email
                user.is_staff = u_info.get("is_staff", user.is_staff)
                user.is_superuser = u_info.get("is_superuser", user.is_superuser)
                user.save()

            prof_data = u_info.get("profile")
            if prof_data:
                prof, _ = Profile.objects.get_or_create(user=user)
                prof.daily_limit = prof_data.get("daily_limit", prof.daily_limit)
                prof.accent = prof_data.get("accent", prof.accent)
                prof.timezone = prof_data.get("timezone", prof.timezone)
                prof.ai_example_enabled = prof_data.get("ai_example_enabled", prof.ai_example_enabled)
                prof.reminder_enabled = prof_data.get("reminder_enabled", prof.reminder_enabled)
                if prof_data.get("telegram_chat_id"):
                    prof.telegram_chat_id = prof_data["telegram_chat_id"]
                prof.save()

            users_by_identifier[email] = user
            users_by_identifier[username] = user
            stats["users"] += 1

        # 3. Restore Texts
        texts_map = {}
        for t_info in data.get("texts", []):
            user_ident = t_info["user_email"]
            user = users_by_identifier.get(user_ident) or User.objects.filter(email=user_ident).first() or User.objects.filter(username=user_ident).first()
            if not user:
                continue

            text_obj, _ = Text.objects.update_or_create(
                user=user,
                title=t_info["title"],
                defaults={"body": t_info["body"]},
            )
            texts_map[(user.id, t_info["title"])] = text_obj
            stats["texts"] += 1

        # 4. Restore Cards
        for c_info in data.get("cards", []):
            user_ident = c_info["user_email"]
            user = users_by_identifier.get(user_ident) or User.objects.filter(email=user_ident).first() or User.objects.filter(username=user_ident).first()
            if not user:
                continue

            src_title = c_info.get("source_text_title")
            source_text = texts_map.get((user.id, src_title)) if src_title else None

            from datetime import date
            next_d = date.fromisoformat(c_info["next_review_date"]) if c_info.get("next_review_date") else None
            last_d = date.fromisoformat(c_info["last_reviewed_date"]) if c_info.get("last_reviewed_date") else None

            WordCard.objects.update_or_create(
                user=user,
                word=c_info["word"],
                context_sentence=c_info.get("context_sentence", ""),
                defaults={
                    "source_text": source_text,
                    "lemma": c_info.get("lemma", ""),
                    "pos": c_info.get("pos", ""),
                    "meaning": c_info.get("meaning", ""),
                    "ctx_start": c_info.get("ctx_start", 0),
                    "ctx_end": c_info.get("ctx_end", len(c_info["word"])),
                    "char_start": c_info.get("char_start"),
                    "char_end": c_info.get("char_end"),
                    "ai_example": c_info.get("ai_example", ""),
                    "audio_url_uk": c_info.get("audio_url_uk", ""),
                    "audio_url_us": c_info.get("audio_url_us", ""),
                    "stage": c_info.get("stage", 0),
                    "target_type": c_info.get("target_type", 1),
                    "interval_days": c_info.get("interval_days", 0),
                    "next_review_date": next_d,
                    "last_reviewed_date": last_d,
                    "consecutive_wrong": c_info.get("consecutive_wrong", 0),
                    "weak_indices": c_info.get("weak_indices") or [],
                    "is_suspended": c_info.get("is_suspended", False),
                },
            )
            stats["cards"] += 1

    return stats


# =====================================================================
# 2. User Personal Backup (Vocab & Texts Only - No Credentials)
# =====================================================================

def generate_user_backup_dict(user: User) -> Dict[str, Any]:
    """Exports only the user's texts and cards without any account settings."""
    texts_data = []
    for t in Text.objects.filter(user=user):
        texts_data.append({
            "title": t.title,
            "body": t.body,
            "created_at": t.created_at.isoformat(),
        })

    cards_data = []
    for c in WordCard.objects.filter(user=user).select_related("source_text"):
        cards_data.append({
            "word": c.word,
            "lemma": c.lemma,
            "pos": c.pos,
            "meaning": c.meaning,
            "context_sentence": c.context_sentence,
            "ctx_start": c.ctx_start,
            "ctx_end": c.ctx_end,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "source_text_title": c.source_text.title if c.source_text else None,
            "stage": c.stage,
            "target_type": c.target_type,
            "interval_days": c.interval_days,
            "next_review_date": c.next_review_date.isoformat() if c.next_review_date else None,
            "last_reviewed_date": c.last_reviewed_date.isoformat() if c.last_reviewed_date else None,
            "consecutive_wrong": c.consecutive_wrong,
            "weak_indices": c.weak_indices,
            "is_suspended": c.is_suspended,
            "ai_example": c.ai_example,
            "audio_url_us": c.audio_url_us,
            "audio_url_uk": c.audio_url_uk,
        })

    return {
        "export_type": "nightly_vocab_user_personal_data",
        "version": "1.0",
        "exported_at": timezone.now().isoformat(),
        "user_email": user.email or user.username,
        "texts": texts_data,
        "cards": cards_data,
    }


def restore_user_backup(user: User, data: Dict[str, Any], reset_review: bool = True) -> Dict[str, int]:
    """
    Imports vocabulary and texts into the specified user's account safely:
    - Never overwrites or deletes existing texts or cards.
    - If a text or card already exists, it is preserved without modification.
    - Only adds genuinely new texts and new cards.
    - If reset_review is True, sets stage=0 and interval_days=0 for fresh learning from today.
    - If reset_review is False, retains the saved SRS review stages and intervals.
    - Never touches user credentials, emails, passwords, or profile configurations.
    """
    if data.get("export_type") not in (
        "nightly_vocab_user_personal_data",
        "nightly_vocab_system_full_backup",
        "lexicontext_user_personal_data",
        "lexicontext_system_full_backup",
    ):
        raise ValueError("فرمت فایل پشتیبان نامعتبر است.")

    stats = {
        "texts": 0,
        "cards": 0,
        "new_texts": 0,
        "existing_texts": 0,
        "new_cards": 0,
        "existing_cards": 0,
    }

    now_date = timezone.localdate()

    with transaction.atomic():
        # 1. Safely import texts (do not overwrite existing ones)
        texts_map = {}
        for t_info in data.get("texts", []):
            title = t_info.get("title", "").strip()
            body = t_info.get("body", "").strip()
            if not title or not body:
                continue

            existing_text = Text.objects.filter(user=user, title=title).first()
            if existing_text:
                texts_map[title] = existing_text
                stats["existing_texts"] += 1
            else:
                new_text = Text.objects.create(
                    user=user,
                    title=title,
                    body=body,
                )
                texts_map[title] = new_text
                stats["new_texts"] += 1

        # 2. Safely import cards (do not overwrite existing ones)
        for c_info in data.get("cards", []):
            word = c_info.get("word", "").strip()
            if not word:
                continue

            context_sentence = c_info.get("context_sentence", "")

            # Check if card already exists for this user (prevent duplicate/replacement)
            card_q = WordCard.objects.filter(user=user, word=word)
            if context_sentence:
                card_q = card_q.filter(context_sentence=context_sentence)

            if card_q.exists():
                stats["existing_cards"] += 1
                continue

            src_title = c_info.get("source_text_title")
            source_text = texts_map.get(src_title)

            # Determine SRS parameters based on reset_review setting
            if reset_review:
                stage = 0
                target_type = 1
                interval_days = 0
                next_review_date = now_date
                last_reviewed_date = None
                consecutive_wrong = 0
                weak_indices = []
            else:
                stage = int(c_info.get("stage", 0))
                target_type = int(c_info.get("target_type", 1))
                interval_days = int(c_info.get("interval_days", 0))

                next_d_str = c_info.get("next_review_date")
                next_review_date = now_date
                if next_d_str:
                    try:
                        next_review_date = datetime.fromisoformat(next_d_str).date()
                    except Exception:
                        next_review_date = now_date

                last_d_str = c_info.get("last_reviewed_date")
                last_reviewed_date = None
                if last_d_str:
                    try:
                        last_reviewed_date = datetime.fromisoformat(last_d_str).date()
                    except Exception:
                        last_reviewed_date = None

                consecutive_wrong = int(c_info.get("consecutive_wrong", 0))
                weak_indices = c_info.get("weak_indices") or []

            WordCard.objects.create(
                user=user,
                source_text=source_text,
                word=word,
                lemma=c_info.get("lemma", ""),
                pos=c_info.get("pos", ""),
                meaning=c_info.get("meaning", ""),
                context_sentence=context_sentence,
                ctx_start=c_info.get("ctx_start", 0),
                ctx_end=c_info.get("ctx_end", len(word)),
                char_start=c_info.get("char_start"),
                char_end=c_info.get("char_end"),
                stage=stage,
                target_type=target_type,
                interval_days=interval_days,
                next_review_date=next_review_date,
                last_reviewed_date=last_reviewed_date,
                consecutive_wrong=consecutive_wrong,
                weak_indices=weak_indices,
                is_suspended=bool(c_info.get("is_suspended", False)),
                ai_example=c_info.get("ai_example", ""),
                audio_url_us=c_info.get("audio_url_us", ""),
                audio_url_uk=c_info.get("audio_url_uk", ""),
            )
            stats["new_cards"] += 1

        stats["texts"] = stats["new_texts"]
        stats["cards"] = stats["new_cards"]

    return stats
