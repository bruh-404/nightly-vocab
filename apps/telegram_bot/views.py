"""Webhook view for handling incoming Telegram Bot updates (Section 5.3 & 7.3)."""
import json
import logging
import re
import zoneinfo
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import Profile
from apps.accounts.views import calculate_user_rank, compute_user_streak
from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.services.models import SiteConfig, UserControl
from apps.telegram_bot.client import BotBlocked, BotNotConfigured, TelegramClient, TelegramError

logger = logging.getLogger(__name__)


def check_telegram_rate_limit(chat_id: int | str, config: SiteConfig) -> Tuple[bool, bool, str]:
    """
    Evaluates anti-spam rate limiting for incoming updates.
    Returns:
      (is_allowed, is_first_limit_violation, reset_str)
    """
    limit = config.tg_user_rate_limit
    if not limit or limit <= 0:
        return True, False, ""

    now = timezone.now()
    rate_type = config.tg_rate_limit_type or "daily"

    if rate_type == "hourly":
        window_tag = now.strftime("%Y%m%d%H")
        reset_dt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        reset_str = f"ساعت {reset_dt.strftime('%H:00')} (حدوداً {max(1, int((reset_dt - now).total_seconds() // 60))} دقیقه دیگر)"
        ttl = max(60, int((reset_dt - now).total_seconds()) + 5)
    else:  # daily
        window_tag = now.strftime("%Y%m%d")
        reset_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        reset_str = f"فردا ساعت 00:00 (تاریخ {reset_dt.strftime('%Y-%m-%d')})"
        ttl = max(300, int((reset_dt - now).total_seconds()) + 5)

    counter_key = f"tg_rl_{chat_id}_{window_tag}"
    warned_key = f"tg_rl_warned_{chat_id}_{window_tag}"

    current_count = cache.get(counter_key, 0) + 1
    cache.set(counter_key, current_count, timeout=ttl)

    if current_count <= limit:
        return True, False, ""

    already_warned = cache.get(warned_key, False)
    if not already_warned:
        cache.set(warned_key, True, timeout=ttl)
        return False, True, reset_str

    return False, False, reset_str


def build_status_message_and_markup(profile: Profile, site_url: str) -> Tuple[str, Dict[str, Any]]:
    """
    Builds the user's learning assessment, rank tier, today's review status,
    and reminder time configuration message with inline buttons.
    """
    try:
        tz = zoneinfo.ZoneInfo(profile.timezone)
    except Exception:
        tz = zoneinfo.ZoneInfo("Asia/Tehran")
    local_now = datetime.now(tz)
    local_today = local_now.date()

    streak = compute_user_streak(profile.user, local_today)
    total_cards = WordCard.objects.filter(user=profile.user, is_suspended=False).count()
    learned_words = WordCard.objects.filter(user=profile.user, is_suspended=False, stage__gte=5).count()
    total_reviews = ReviewLog.objects.filter(user=profile.user).count()

    rank_info = calculate_user_rank(streak, total_cards, learned_words, total_reviews)

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

    remaining = max(0, session_total - reviewed_today)
    reminder_str = profile.reminder_time.strftime("%H:%M") if profile.reminder_time else "21:00"

    lines = [
        "📊 <b>ارزیابی و وضعیت یادگیری شما:</b>\n",
        f"🎖️ <b>سطح و رنک:</b> {rank_info['icon']} <b>{rank_info['tier_name']}</b> {rank_info['stars_display']}",
        f"⭐ <b>امتیاز رنک (MMR):</b> {rank_info['score']:,}",
        f"🔥 <b>استمرار روزانه:</b> {rank_info['streak_days']} روز متوالی",
        f"📚 <b>کل واژگان فعال:</b> {total_cards} واژه",
        f"🎓 <b>واژگان مسلط‌شده:</b> {learned_words} واژه",
        f"🔁 <b>مجموع مرورها:</b> {total_reviews:,}",
    ]

    if rank_info.get("next_tier_name") and rank_info.get("pts_needed"):
        lines.append(f"🎯 <b>تا رنک بعدی ({rank_info['next_tier_name']}):</b> {rank_info['pts_needed']:,} امتیاز")

    lines.append("\n───────────────")
    lines.append("📅 <b>وضعیت مرور امروز:</b>")

    if session_total == 0:
        lines.append("🎉 امروز هیچ کارت جدید یا مروری در نوبت ندارید! می‌توانید واژگان جدید به متن‌هایتان اضافه کنید.")
    elif remaining == 0:
        lines.append(f"✅ <b>مرور امروز کامل شده است!</b> ({reviewed_today} از {session_total} کارت)")
        lines.append("عالی پیش می‌روید؛ زنجیره استمرار شما برای امروز تثبیت شد.")
    else:
        lines.append(f"⏳ <b>{remaining}</b> کارت از {session_total} کارت امروز باقی مانده است.")
        lines.append(f"انجام شده: {reviewed_today} کارت | باقیمانده: {remaining} کارت")

    lines.append("\n───────────────")
    lines.append(f"⏰ <b>ساعت یادآوری امروز: {reminder_str}</b>")
    lines.append(
        "\n💡 <i>نکته: شما موظف نیستید حتماً در این ساعت به سایت مراجعه کنید؛ در هر زمانی از امروز یا روز بعد می‌توانید مرور را انجام دهید. با این حال، اگر تا فرا رسیدن ساعت یادآوری مرور نکرده باشید، جهت جلوگیری از قطع استمرار نوتیف تلگرام برای شما ارسال خواهد شد.</i>"
    )
    lines.append("\n⚙️ <b>برای تغییر ساعت یادآوری، یکی از گزینه‌های زیر را لمس کنید یا دستور <code>/time HH:MM</code> را ارسال فرمایید (مثلاً: <code>/time 22:30</code>):</b>")

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "⏰ 20:00", "callback_data": "set_time:20:00"},
                {"text": "⏰ 21:00", "callback_data": "set_time:21:00"},
                {"text": "⏰ 22:00", "callback_data": "set_time:22:00"},
                {"text": "⏰ 23:00", "callback_data": "set_time:23:00"},
            ],
            [
                {"text": "⏰ 08:00", "callback_data": "set_time:08:00"},
                {"text": "⏰ 12:00", "callback_data": "set_time:12:00"},
                {"text": "⏰ 18:00", "callback_data": "set_time:18:00"},
                {"text": "⏰ 19:00", "callback_data": "set_time:19:00"},
            ],
            [
                {"text": "🚀 شروع مرور در وب‌سایت", "url": f"{site_url.rstrip('/')}/review/"}
            ],
        ]
    }

    return "\n".join(lines), reply_markup


def check_user_membership(user_id: int | str, config: SiteConfig, client: TelegramClient) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Checks if user is a member of all required channels/groups when Force Join is enabled.
    Returns:
      (is_member: bool, error_message: str | None, reply_markup: dict | None)
    """
    if not config.tg_force_join_enabled:
        return True, None, None

    targets = config.get_force_join_channels()
    if not targets:
        return True, None, None

    missing_channels = []
    for t in targets:
        ch = t.get("channel", "").strip()
        if not ch:
            continue
        try:
            res = client.get_chat_member(chat_id=ch, user_id=user_id)
            status = res.get("status", "")
            is_mem = status in ["creator", "administrator", "member"] or (status == "restricted" and res.get("is_member", True))
            if not is_mem:
                missing_channels.append(t)
        except Exception as exc:
            logger.warning("Could not check chat member status for user %s in %s: %s", user_id, ch, exc)

    if not missing_channels:
        return True, None, None

    buttons = []
    for t in missing_channels:
        ch_title = t.get("title") or t.get("channel")
        link = t.get("link")
        if not link:
            clean_name = t.get("channel", "").lstrip("@")
            link = f"https://t.me/{clean_name}"
        buttons.append([{"text": f"📢 عضویت در {ch_title}", "url": link}])

    buttons.append([{"text": "🔄 تایید و بررسی مجدد", "callback_data": "check_membership"}])

    channel_count_str = f"<b>{len(missing_channels)}</b> کانال/گروه" if len(missing_channels) > 1 else "کانال/گروه"
    msg_text = (
        f"⚠️ <b>عضویت در کانال‌های زیر الزامی است!</b>\n\n"
        f"برای استفاده از خدمات ربات، لطفاً ابتدا در {channel_count_str} مشخص‌شده عضو شوید و سپس دکمه <b>«تایید و بررسی مجدد»</b> را لمس کنید."
    )
    markup = {"inline_keyboard": buttons}
    return False, msg_text, markup


@csrf_exempt
@require_POST
def telegram_webhook_view(request: HttpRequest) -> JsonResponse:
    """
    Handles incoming webhook updates from Telegram.
    Verifies X-Telegram-Bot-Api-Secret-Token header against SiteConfig.
    Enforces configurable anti-spam rate limiting.
    Handles /start <token>, /stop, /status, /time commands and interactive callback queries.
    """
    config = SiteConfig.get()
    expected_secret = config.get_tg_webhook_secret()

    # Secret token check
    provided_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if expected_secret and provided_secret != expected_secret:
        logger.warning("Telegram webhook secret mismatch: provided %r", provided_secret)
        return HttpResponseForbidden("Invalid secret token")

    try:
        update = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        client = TelegramClient()
    except BotNotConfigured:
        return JsonResponse({"ok": True})

    # 1. Handle Callback Query (e.g. set_time:21:00)
    callback_query = update.get("callback_query")
    if callback_query:
        cq_id = callback_query.get("id")
        data = (callback_query.get("data") or "").strip()
        chat = callback_query.get("message", {}).get("chat", {})
        chat_id = chat.get("id") or callback_query.get("from", {}).get("id")

        if not chat_id:
            return JsonResponse({"ok": True})

        # Anti-spam rate limiting
        is_allowed, is_first_violation, reset_str = check_telegram_rate_limit(chat_id, config)
        if not is_allowed:
            if is_first_violation:
                try:
                    limit_desc = f"{config.tg_user_rate_limit} پیام"
                    period_desc = "این ساعت" if config.tg_rate_limit_type == "hourly" else "امروز"
                    client.answer_callback_query(
                        callback_query_id=cq_id,
                        text=f"سقف مجاز ارسال پیام ({limit_desc}) تکمیل شد.",
                        show_alert=True,
                    )
                    client.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ <b>محدودیت تعداد پیام!</b>\n\nشما به سقف مجاز پیام در {period_desc} ({limit_desc}) رسیده‌اید.\nپیام‌های شما تا <b>{reset_str}</b> نادیده گرفته خواهند شد.",
                    )
                except Exception:
                    pass
            return JsonResponse({"ok": True})

        try:
            if data.startswith("set_time:"):
                time_val = data.split(":", 1)[1].strip()
                m = re.match(r"^(\d{1,2}):(\d{2})$", time_val)
                if m:
                    h, min_val = int(m.group(1)), int(m.group(2))
                    profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
                    if profile:
                        profile.reminder_time = time(h, min_val)
                        profile.reminder_enabled = True
                        profile.save(update_fields=["reminder_time", "reminder_enabled"])
                        client.answer_callback_query(
                            callback_query_id=cq_id,
                            text=f"ساعت یادآوری روی {time_val} تنظیم شد ✅",
                        )
                        client.send_message(
                            chat_id=chat_id,
                            text=f"✅ <b>ساعت یادآوری شما با موفقیت روی {time_val} تنظیم شد.</b>\n\n💡 اگر تا این ساعت مرور خود را انجام نداده باشید، پیام یادآوری برای شما ارسال خواهد شد. در هر ساعت دلخواه دیگری نیز می‌توانید مرور خود را انجام دهید.",
                        )
                    else:
                        client.answer_callback_query(
                            callback_query_id=cq_id,
                            text="حساب کاربری متصل نیست.",
                            show_alert=True,
                        )
            elif data == "check_membership":
                is_mem, _, _ = check_user_membership(chat_id, config, client)
                if is_mem:
                    client.answer_callback_query(
                        callback_query_id=cq_id,
                        text="عضویت شما با موفقیت تایید شد! ✅",
                        show_alert=True,
                    )
                    profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
                    if profile:
                        status_text, reply_markup = build_status_message_and_markup(profile, site_url)
                        client.send_message(
                            chat_id=chat_id,
                            text=f"خوش آمدید! 🎉\n\n{status_text}",
                            reply_markup=reply_markup,
                        )
                    else:
                        client.send_message(
                            chat_id=chat_id,
                            text="عضویت شما تایید شد! برای اتصال این ربات به حسابتان، لطفاً وارد پنل کاربری در وب‌سایت شوید.",
                        )
                else:
                    client.answer_callback_query(
                        callback_query_id=cq_id,
                        text="شما هنوز در کانال عضو نشده‌اید! لطفاً ابتدا عضو شوید.",
                        show_alert=True,
                    )
        except BotBlocked:
            logger.info("User %s has blocked the bot during callback query.", chat_id)
        except TelegramError as exc:
            logger.warning("Error processing callback query update: %s", exc)

        return JsonResponse({"ok": True})

    # 2. Handle Message
    message = update.get("message")
    if not message:
        return JsonResponse({"ok": True})

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return JsonResponse({"ok": True})

    # Anti-spam rate limiting
    is_allowed, is_first_violation, reset_str = check_telegram_rate_limit(chat_id, config)
    if not is_allowed:
        if is_first_violation:
            try:
                limit_desc = f"{config.tg_user_rate_limit} پیام"
                period_desc = "این ساعت" if config.tg_rate_limit_type == "hourly" else "امروز"
                client.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ <b>محدودیت تعداد پیام!</b>\n\nشما به سقف مجاز پیام در {period_desc} ({limit_desc}) رسیده‌اید.\nپیام‌های شما تا <b>{reset_str}</b> نادیده گرفته خواهند شد.",
                )
            except Exception:
                pass
        return JsonResponse({"ok": True})

    site_url = getattr(settings, "SITE_URL", "http://localhost:8000")

    try:
        # Force join channel check (skip for /stop so user can always unlink)
        if not text.startswith("/stop"):
            is_mem, force_msg, force_markup = check_user_membership(chat_id, config, client)
            if not is_mem:
                client.send_message(
                    chat_id=chat_id,
                    text=force_msg,
                    reply_markup=force_markup,
                )
                return JsonResponse({"ok": True})

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            token = parts[1].strip() if len(parts) > 1 else None

            if token:
                profile = Profile.objects.filter(telegram_link_token=token).first()
                if profile:
                    # Check administrator access control
                    control = UserControl.objects.filter(user=profile.user).first()
                    if control and (control.is_blocked or control.telegram_access == "blocked"):
                        client.send_message(
                            chat_id=chat_id,
                            text="⚠️ دسترسی شما به خدمات تلگرام توسط مدیر سامانه محدود شده است.",
                        )
                    else:
                        profile.telegram_chat_id = chat_id
                        profile.reminder_enabled = True
                        profile.telegram_link_token = None
                        profile.save(update_fields=["telegram_chat_id", "reminder_enabled", "telegram_link_token"])

                        status_text, reply_markup = build_status_message_and_markup(profile, site_url)
                        welcome_text = "✅ <b>حساب کاربری شما با موفقیت متصل شد!</b>\n\n" + status_text
                        client.send_message(
                            chat_id=chat_id,
                            text=welcome_text,
                            reply_markup=reply_markup,
                        )
                else:
                    client.send_message(
                        chat_id=chat_id,
                        text="❌ لینک اتصال نامعتبر یا منقضی شده است. لطفاً از بخش تنظیمات در وب‌سایت مجدداً اقدام کنید.",
                    )
            else:
                # Bare /start
                existing_profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
                if existing_profile:
                    status_text, reply_markup = build_status_message_and_markup(existing_profile, site_url)
                    client.send_message(
                        chat_id=chat_id,
                        text=status_text,
                        reply_markup=reply_markup,
                    )
                else:
                    client.send_message(
                        chat_id=chat_id,
                        text="سلام! برای اتصال این ربات به حساب کاربری خود در سامانه <b>LexiContext</b>، لطفاً وارد بخش تنظیمات در وب‌سایت شده و روی «اتصال به تلگرام» کلیک کنید.",
                    )

        elif text.startswith("/stop"):
            profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
            if profile:
                profile.telegram_chat_id = None
                profile.reminder_enabled = False
                profile.save(update_fields=["telegram_chat_id", "reminder_enabled"])

                client.send_message(
                    chat_id=chat_id,
                    text="اتصال حساب شما با موفقیت قطع شد و ارسال یادآوری‌ها متوقف گردید.",
                )
            else:
                client.send_message(
                    chat_id=chat_id,
                    text="حساب کاربری متصلی برای این چت یافت نشد.",
                )

        elif any(text.startswith(cmd) for cmd in ["/status", "/profile", "/me", "/rank", "/level"]):
            profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
            if profile:
                status_text, reply_markup = build_status_message_and_markup(profile, site_url)
                client.send_message(
                    chat_id=chat_id,
                    text=status_text,
                    reply_markup=reply_markup,
                )
            else:
                client.send_message(
                    chat_id=chat_id,
                    text="⚠️ حساب کاربری متصلی برای این چت یافت نشد.\n\nلطفاً از طریق وب‌سایت وارد حساب خود شده و از بخش تنظیمات ربات را متصل فرمایید.",
                )

        elif text.startswith("/time"):
            profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
            if not profile:
                client.send_message(
                    chat_id=chat_id,
                    text="⚠️ حساب کاربری متصلی برای این چت یافت نشد. لطفاً ابتدا حساب خود را در وب‌سایت متصل نمایید.",
                )
            else:
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    time_raw = parts[1].strip()
                    m = re.match(r"^(\d{1,2})[:.](\d{2})$", time_raw)
                    if m:
                        h, min_val = int(m.group(1)), int(m.group(2))
                        if 0 <= h <= 23 and 0 <= min_val <= 59:
                            profile.reminder_time = time(h, min_val)
                            profile.reminder_enabled = True
                            profile.save(update_fields=["reminder_time", "reminder_enabled"])
                            time_str = profile.reminder_time.strftime("%H:%M")
                            client.send_message(
                                chat_id=chat_id,
                                text=f"✅ <b>ساعت یادآوری با موفقیت روی {time_str} تنظیم شد.</b>\n\n💡 در صورتی که تا این ساعت مرور نکرده باشید، اعلان یادآوری ارسال خواهد شد. در هر ساعت دیگری از شبانه‌روز نیز می‌توانید مرور خود را آزادانه انجام دهید.",
                            )
                        else:
                            client.send_message(
                                chat_id=chat_id,
                                text="⚠️ ساعت یا دقیقه نامعتبر است. ساعت باید بین 00 تا 23 و دقیقه بین 00 تا 59 باشد.",
                            )
                    else:
                        client.send_message(
                            chat_id=chat_id,
                            text="⚠️ فرمت ساعت وارد شده صحیح نیست. لطفاً به فرمت HH:MM ارسال کنید.\nمثال: <code>/time 21:30</code>",
                        )
                else:
                    current_t = profile.reminder_time.strftime("%H:%M") if profile.reminder_time else "21:00"
                    quick_markup = {
                        "inline_keyboard": [
                            [
                                {"text": "⏰ 20:00", "callback_data": "set_time:20:00"},
                                {"text": "⏰ 21:00", "callback_data": "set_time:21:00"},
                                {"text": "⏰ 22:00", "callback_data": "set_time:22:00"},
                                {"text": "⏰ 23:00", "callback_data": "set_time:23:00"},
                            ],
                            [
                                {"text": "⏰ 08:00", "callback_data": "set_time:08:00"},
                                {"text": "⏰ 12:00", "callback_data": "set_time:12:00"},
                                {"text": "⏰ 18:00", "callback_data": "set_time:18:00"},
                                {"text": "⏰ 19:00", "callback_data": "set_time:19:00"},
                            ]
                        ]
                    }
                    client.send_message(
                        chat_id=chat_id,
                        text=f"⏰ ساعت یادآوری فعلی شما: <b>{current_t}</b> است.\n\nبرای تغییر ساعت، یکی از گزینه‌های زیر را لمس کرده یا دستور را به صورت <code>/time HH:MM</code> ارسال کنید (مثال: <code>/time 22:30</code>):",
                        reply_markup=quick_markup,
                    )

        else:
            # General text
            profile = Profile.objects.filter(telegram_chat_id=chat_id).first()
            if profile:
                status_text, reply_markup = build_status_message_and_markup(profile, site_url)
                client.send_message(
                    chat_id=chat_id,
                    text=f"سلام! 👋\n\n{status_text}",
                    reply_markup=reply_markup,
                )
            else:
                client.send_message(
                    chat_id=chat_id,
                    text="سلام! برای اتصال این ربات به حساب کاربری خود در سامانه <b>LexiContext</b>، لطفاً وارد پنل کاربری در وب‌سایت شده و در بخش تنظیمات روی «اتصال به تلگرام» کلیک کنید.",
                )

    except BotBlocked:
        logger.info("User %s has blocked the bot during webhook response.", chat_id)
    except TelegramError as exc:
        logger.warning("Error processing webhook update: %s", exc)

    return JsonResponse({"ok": True})
