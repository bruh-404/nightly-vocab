"""Views for accounts, dashboard, settings, and learning statistics (Step 8)."""
import json
import secrets
from datetime import date, time, timedelta
from typing import Any, Dict, List
from zoneinfo import available_timezones

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

User = get_user_model()

from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.services.ai.gemini import GeminiProvider
from apps.services.ai.usage import get_user_ai_usage_summary
from apps.services.models import SiteConfig, UserApiKey
from apps.texts.models import Text


def compute_user_streak(user, today: date) -> int:
    """Calculates active consecutive study streak in days."""
    active_dates = set(
        ReviewLog.objects.filter(user=user)
        .values_list("local_date", flat=True)
        .distinct()
    )
    streak = 0
    check_day = today
    if check_day not in active_dates:
        yesterday = today - timedelta(days=1)
        if yesterday in active_dates:
            check_day = yesterday

    while check_day in active_dates:
        streak += 1
        check_day -= timedelta(days=1)

    return streak


def calculate_user_rank(streak: int, total_cards: int, learned_words: int, total_reviews: int) -> Dict[str, Any]:
    """
    Computes competitive Dota 2 inspired rank tier (Herald -> Immortal).
    Both vocabulary mastery and streak contribute to score.
    Breaking a streak deducts bonus points instead of dropping rank to zero.
    """
    card_score = total_cards * 20
    mastery_score = learned_words * 40
    review_score = total_reviews * 8

    streak_score = streak * 60
    if streak >= 30:
        streak_score += 800
    elif streak >= 14:
        streak_score += 400
    elif streak >= 7:
        streak_score += 150

    total_score = card_score + mastery_score + review_score + streak_score

    TIERS = [
        ("herald", "Herald", "نوآموز (Herald)", 0, 249, "#8b949e", "🛡️"),
        ("guardian", "Guardian", "نگهبان (Guardian)", 250, 599, "#3fb950", "⚔️"),
        ("crusader", "Crusader", "سلحشور (Crusader)", 600, 1199, "#58a6ff", "🗡️"),
        ("archon", "Archon", "پیشرو (Archon)", 1200, 2199, "#a371f7", "👑"),
        ("legend", "Legend", "افسانه‌ای (Legend)", 2200, 3999, "#f85149", "🔥"),
        ("ancient", "Ancient", "کهنه‌کار (Ancient)", 4000, 6499, "#d29922", "🔮"),
        ("divine", "Divine", "فرهیخته (Divine)", 6500, 9999, "#f0883e", "⚡"),
        ("immortal", "Immortal", "جاودان (Immortal)", 10000, 999999, "#ff2a55", "🌟"),
    ]

    current_tier = TIERS[0]
    next_tier = None
    for i, t in enumerate(TIERS):
        if total_score >= t[3]:
            current_tier = t
            if i + 1 < len(TIERS):
                next_tier = TIERS[i + 1]
            else:
                next_tier = None

    tier_range = (current_tier[4] - current_tier[3]) if current_tier[4] != 999999 else 2500
    points_in_tier = max(0, total_score - current_tier[3])
    star_step = max(1, tier_range / 5)
    stars = min(5, max(1, int(points_in_tier / star_step) + 1)) if current_tier[0] != "immortal" else 5

    if next_tier:
        progress_pct = min(100, max(0, int((points_in_tier / tier_range) * 100)))
        pts_needed = max(0, next_tier[3] - total_score)
    else:
        progress_pct = 100
        pts_needed = 0

    return {
        "score": total_score,
        "tier_name": current_tier[1],
        "tier_persian": current_tier[2],
        "tier_id": current_tier[0],
        "color": current_tier[5],
        "icon": current_tier[6],
        "stars": stars,
        "stars_display": "★" * stars,
        "progress_pct": progress_pct,
        "pts_needed": pts_needed,
        "next_tier_name": next_tier[1] if next_tier else "Top Rank",
        "streak_days": streak,
    }


@login_required
@require_GET
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    Dashboard view showing today's numbers, start review call-to-action,
    backlog / recovery alert, and recent texts.
    """
    user = request.user
    profile = user.profile
    today = profile.get_local_date()

    # Cards counts
    due_cards_count = WordCard.objects.filter(
        user=user,
        is_suspended=False,
        stage__gt=0,
        next_review_date__lte=today,
    ).count()

    new_cards_count = WordCard.objects.filter(
        user=user,
        is_suspended=False,
        stage=0,
    ).count()

    reviewed_today_count = ReviewLog.objects.filter(
        user=user,
        local_date=today,
    ).count()

    session = DailySession.objects.filter(user=user, local_date=today).first()
    if session:
        session_total = len(session.card_ids)
    else:
        session_total = min(profile.daily_limit, due_cards_count + new_cards_count)

    session_done = reviewed_today_count >= session_total if session_total > 0 else True
    remaining_today = max(0, session_total - reviewed_today_count)

    # Absence / Backlog recovery check (7+ days absent)
    is_recovery = False
    if profile.last_active_date:
        days_absent = (today - profile.last_active_date).days
        if days_absent >= 7:
            is_recovery = True

    overdue_cards_count = WordCard.objects.filter(
        user=user,
        is_suspended=False,
        stage__gt=0,
        next_review_date__lt=today,
    ).count()

    # Recent texts
    recent_texts = Text.objects.filter(user=user).annotate(
        cards_count=Count("cards")
    ).order_by("-created_at")[:5]

    # Rank & streak
    streak = compute_user_streak(user, today)
    total_cards = WordCard.objects.filter(user=user).count()
    learned_words_count = WordCard.objects.filter(user=user, stage__gte=6).count()
    total_reviews = ReviewLog.objects.filter(user=user).count()
    user_rank = calculate_user_rank(streak, total_cards, learned_words_count, total_reviews)

    return render(
        request,
        "dashboard.html",
        {
            "profile": profile,
            "today": today,
            "due_cards_count": due_cards_count,
            "new_cards_count": new_cards_count,
            "reviewed_today_count": reviewed_today_count,
            "session_total": session_total,
            "remaining_today": remaining_today,
            "session_done": session_done,
            "is_recovery": is_recovery,
            "overdue_cards_count": overdue_cards_count,
            "recent_texts": recent_texts,
            "streak": streak,
            "user_rank": user_rank,
            "title": "داشبورد مطالعه | Nightly Vocab",
        },
    )


@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    """
    Settings view handling SRS preferences, enabled card types, AI settings (BYOK),
    Telegram reminders, and account options.
    """
    user = request.user
    profile = user.profile
    config = SiteConfig.get()
    error_message = None
    success_message = None

    if request.method == "POST":
        action = request.POST.get("action", "save_general")

        if action == "save_general":
            try:
                # 1. Daily limit
                daily_limit = int(request.POST.get("daily_limit", profile.daily_limit))
                valid_limits = [c[0] for c in profile.DAILY_LIMIT_CHOICES]
                if daily_limit in valid_limits:
                    profile.daily_limit = daily_limit

                # 2. Enabled card types (must have at least one)
                raw_types = request.POST.getlist("enabled_card_types")
                selected_types = [int(t) for t in raw_types if t.isdigit() and int(t) in (1, 2, 3)]
                if not selected_types:
                    error_message = "حداقل یک نوع کارت باید فعال باشد."
                else:
                    profile.enabled_card_types = selected_types

                # 3. AI Extra Example toggle
                profile.ai_example_enabled = "ai_example_enabled" in request.POST

                # 4. Accent
                accent = request.POST.get("accent", profile.accent)
                if accent in ("uk", "us"):
                    profile.accent = accent

                # 5. Timezone
                tz_name = request.POST.get("timezone", profile.timezone).strip()
                if tz_name in available_timezones():
                    profile.timezone = tz_name

                # 6. Telegram reminders
                profile.reminder_enabled = "reminder_enabled" in request.POST
                raw_time = request.POST.get("reminder_time", "").strip()
                if raw_time:
                    try:
                        t_parts = [int(p) for p in raw_time.split(":")]
                        profile.reminder_time = time(t_parts[0], t_parts[1])
                    except Exception:
                        pass

                # 7. Telegram chat ID manual update
                raw_chat_id = request.POST.get("telegram_chat_id", "").strip()
                if raw_chat_id:
                    if raw_chat_id.isdigit():
                        profile.telegram_chat_id = int(raw_chat_id)
                elif "telegram_chat_id" in request.POST:
                    profile.telegram_chat_id = None

                if not error_message:
                    profile.save()
                    success_message = "تنظیمات با موفقیت ذخیره شد."
            except Exception as exc:
                error_message = f"خطا در ذخیره تنظیمات: {exc}"

    today = profile.get_local_date()
    ai_summary = get_user_ai_usage_summary(user, local_date=today)
    user_api_key = UserApiKey.objects.filter(user=user, provider=config.ai_provider).first()

    # Timezones list for dropdown
    popular_tzs = [
        ("Asia/Tehran", "ایران (تهران) — Asia/Tehran"),
        ("UTC", "ساعت جهانی — UTC"),
        ("Europe/London", "انگلستان (لندن) — Europe/London"),
        ("Europe/Berlin", "اروپا (برلین) — Europe/Berlin"),
        ("Europe/Paris", "اروپا (پاریس) — Europe/Paris"),
        ("America/New_York", "آمریکا (نیویورک) — America/New_York"),
        ("America/Los_Angeles", "آمریکا (لس‌آنجلس) — America/Los_Angeles"),
        ("Asia/Dubai", "امارات (دبی) — Asia/Dubai"),
        ("Asia/Istanbul", "ترکیه (استانبول) — Asia/Istanbul"),
        ("Australia/Sydney", "استرالیا (سیدنی) — Australia/Sydney"),
        ("America/Toronto", "کانادا (تورنتو) — America/Toronto"),
    ]

    # Ensure user has a valid telegram_link_token for deep-link linking
    if not profile.telegram_link_token:
        profile.telegram_link_token = secrets.token_urlsafe(24)
        profile.save(update_fields=["telegram_link_token"])

    tg_bot_username = config.tg_bot_username or getattr(settings, "TELEGRAM_BOT_USERNAME", "")
    tg_deep_link = (
        f"https://t.me/{tg_bot_username}?start={profile.telegram_link_token}"
        if tg_bot_username
        else ""
    )

    try:
        from allauth.socialaccount.models import SocialAccount
        google_account = SocialAccount.objects.filter(user=user, provider="google").first()
    except Exception:
        google_account = None

    return render(
        request,
        "settings/index.html",
        {
            "profile": profile,
            "config": config,
            "ai_summary": ai_summary,
            "user_api_key": user_api_key,
            "popular_tzs": popular_tzs,
            "tg_bot_username": tg_bot_username,
            "tg_deep_link": tg_deep_link,
            "google_account": google_account,
            "error_message": error_message,
            "success_message": success_message,
            "title": "تنظیمات حساب کاربری | Nightly Vocab",
        },
    )


@login_required
@require_POST
def save_and_test_user_key_api(request: HttpRequest) -> JsonResponse:
    """
    Saves and tests user personal Gemini API key (BYOK flow).
    Validates key against Google Gemini API before saving encrypted.
    """
    try:
        data = json.loads(request.body)
        raw_key = data.get("api_key", "").strip()
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    if not raw_key:
        return JsonResponse({"error": "کلید API الزامی است."}, status=400)

    # Test key with Gemini API
    is_valid, err_msg = GeminiProvider.test_api_key(raw_key)
    if not is_valid:
        return JsonResponse({
            "error": f"کلید نامعتبر است یا ارتباط برقرار نشد: {err_msg}",
        }, status=400)

    config = SiteConfig.get()
    key_obj, _ = UserApiKey.objects.get_or_create(
        user=request.user,
        provider=config.ai_provider,
    )
    key_obj.set_key(raw_key)
    key_obj.enabled = True
    key_obj.validated_at = timezone.now()
    key_obj.last_error = ""
    key_obj.save()

    return JsonResponse({
        "success": True,
        "masked": key_obj.masked(),
        "key_last4": key_obj.key_last4,
    })


@login_required
@require_POST
def toggle_user_key_api(request: HttpRequest) -> JsonResponse:
    """Toggles active status of user's personal API key."""
    config = SiteConfig.get()
    key_obj = UserApiKey.objects.filter(user=request.user, provider=config.ai_provider).first()
    if not key_obj:
        return JsonResponse({"error": "کلیدی ثبت نشده است."}, status=404)

    key_obj.enabled = not key_obj.enabled
    key_obj.save(update_fields=["enabled"])

    return JsonResponse({
        "success": True,
        "enabled": key_obj.enabled,
    })


@login_required
@require_POST
def delete_user_key_api(request: HttpRequest) -> JsonResponse:
    """Deletes user's personal API key permanently."""
    config = SiteConfig.get()
    UserApiKey.objects.filter(user=request.user, provider=config.ai_provider).delete()
    return JsonResponse({"success": True})


@login_required
@require_POST
def disconnect_telegram_api(request: HttpRequest) -> JsonResponse:
    """Disconnects Telegram account from user profile."""
    profile = request.user.profile
    profile.telegram_chat_id = None
    profile.save(update_fields=["telegram_chat_id"])
    return JsonResponse({"success": True})


@login_required
@require_POST
def delete_account_api(request: HttpRequest) -> JsonResponse:
    """
    Schedules user account for permanent deletion with a 24-hour grace period.
    Sends notification email, logs out the user, and redirects to landing page.
    """
    user = request.user
    profile = user.profile
    profile.deletion_requested_at = timezone.now()
    profile.save(update_fields=["deletion_requested_at"])

    # Send confirmation email
    if user.email:
        try:
            from django.core.mail import send_mail
            subject = "درخواست حذف حساب کاربری در سامانه Nightly Vocab"
            message = (
                f"کاربر گرامی {user.username}،\n\n"
                "درخواست حذف حساب کاربری شما با موفقیت ثبت گردید.\n"
                "کلیه اطلاعات، متون و کارت‌های واژگان شما به مدت ۲۴ ساعت (۱ روز) در سرور نگه‌داری می‌شوند.\n"
                "اگر ظرف این ۲۴ ساعت مجدداً به حساب خود وارد شوید، این درخواست به‌طور خودکار لغو شده و حساب شما با تمامی اطلاعات حفظ خواهد شد.\n"
                "در غیر این صورت، پس از ۲۴ ساعت حساب کاربری و تمامی اطلاعات مرتبط با آن به‌صورت دائمی و غیرقابل‌بازگشت از سرور پاک خواهند شد.\n\n"
                "تیم Nightly Vocab"
            )
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@lexicontext.app")
            send_mail(subject, message, from_email, [user.email], fail_silently=True)
        except Exception:
            pass

    logout(request)
    return JsonResponse({
        "success": True,
        "message": "درخواست حذف ثبت شد. تا ۲۴ ساعت فرصت دارید با ورود مجدد آن را لغو کنید.",
        "redirect": "/",
    })


@login_required
@require_GET
def stats_view(request: HttpRequest) -> HttpResponse:
    """
    Simple statistics page showing stage distribution, words learned (stage >= 6),
    30-day review activity history, and current streak.
    """
    user = request.user
    profile = user.profile
    today = profile.get_local_date()

    # 1. Total cards and stage counts
    total_cards = WordCard.objects.filter(user=user).count()
    stage_counts_qs = (
        WordCard.objects.filter(user=user)
        .values("stage")
        .annotate(count=Count("id"))
    )
    stage_counts: Dict[int, int] = dict.fromkeys(range(9), 0)
    for row in stage_counts_qs:
        s = row["stage"]
        if 0 <= s <= 8:
            stage_counts[s] = row["count"]

    # Phases
    new_cards_count = stage_counts[0]
    learning_cards_count = sum(stage_counts[i] for i in (1, 2, 3))
    reviewing_cards_count = sum(stage_counts[i] for i in (4, 5, 6, 7))
    mastered_cards_count = stage_counts[8]
    learned_words_count = sum(stage_counts[i] for i in (6, 7, 8))

    # 2. Total reviews ever recorded
    total_reviews = ReviewLog.objects.filter(user=user).count()

    # 3. Reviews per day in the last 30 days
    start_date = today - timedelta(days=29)
    logs_30d = (
        ReviewLog.objects.filter(user=user, local_date__gte=start_date, local_date__lte=today)
        .values("local_date")
        .annotate(count=Count("id"))
    )
    logs_map = {row["local_date"]: row["count"] for row in logs_30d}

    activity_30d: List[Dict[str, Any]] = []
    max_day_reviews = 1
    for day_offset in range(30):
        d = start_date + timedelta(days=day_offset)
        cnt = logs_map.get(d, 0)
        if cnt > max_day_reviews:
            max_day_reviews = cnt
        activity_30d.append({
            "date": d,
            "formatted_date": d.strftime("%m/%d"),
            "count": cnt,
        })

    # 4. Streak & Rank calculation
    streak = compute_user_streak(user, today)
    user_rank = calculate_user_rank(streak, total_cards, learned_words_count, total_reviews)

    return render(
        request,
        "stats/index.html",
        {
            "total_cards": total_cards,
            "stage_counts": stage_counts,
            "new_cards_count": new_cards_count,
            "learning_cards_count": learning_cards_count,
            "reviewing_cards_count": reviewing_cards_count,
            "mastered_cards_count": mastered_cards_count,
            "learned_words_count": learned_words_count,
            "total_reviews": total_reviews,
            "activity_30d": activity_30d,
            "max_day_reviews": max_day_reviews,
            "streak": streak,
            "user_rank": user_rank,
            "title": "آمار یادگیری و رنک | Nightly Vocab",
        },
    )


@login_required
@require_POST
def timezone_sync_view(request: HttpRequest) -> JsonResponse:
    """Syncs browser detected IANA timezone with user profile."""
    try:
        data = json.loads(request.body)
        tz_name = data.get("timezone", "").strip()
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not tz_name or tz_name not in available_timezones():
        return JsonResponse({"error": "Invalid timezone"}, status=400)

    profile = request.user.profile
    profile.timezone = tz_name
    profile.save(update_fields=["timezone"])

    return JsonResponse({
        "success": True,
        "timezone": profile.timezone,
    })


@login_required
@require_GET
def user_export_backup_api(request: HttpRequest) -> HttpResponse:
    """Exports user's personal texts and cards as a downloadable JSON file."""
    from apps.services.backup_service import generate_user_backup_dict
    data = generate_user_backup_dict(request.user)
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    now_str = timezone.now().strftime("%Y-%m-%d")
    response = HttpResponse(json_bytes, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="my_lexicontext_vocab_{now_str}.json"'
    return response


@login_required
@require_POST
def user_import_backup_api(request: HttpRequest) -> JsonResponse:
    """Imports personal texts and cards from an uploaded JSON backup file."""
    from apps.services.backup_service import restore_user_backup
    backup_file = request.FILES.get("backup_file")
    if not backup_file:
        return JsonResponse({"error": "لطفاً فایل پشتیبان (.json) را انتخاب کنید."}, status=400)

    try:
        content = backup_file.read().decode("utf-8")
        data = json.loads(content)
        reset_review_raw = request.POST.get("reset_review", "true")
        reset_review = str(reset_review_raw).strip().lower() in ("true", "1", "yes")

        stats = restore_user_backup(request.user, data, reset_review=reset_review)

        mode_desc = "شروع یادگیری از ابتدا (مرحله ۰)" if reset_review else "ادامه وضعیت مرور قبلی"
        msg = f"بازیابی با موفقیت انجام شد: {stats['new_texts']} متن جدید و {stats['new_cards']} واژه جدید به حسابتان افزوده شدند ({mode_desc})."
        if stats.get("existing_cards", 0) > 0:
            msg += f" ضمناً {stats['existing_cards']} واژه که قبلاً در حسابتان وجود داشتند بدون تغییر حفظ شدند."

        return JsonResponse({
            "success": True,
            "message": msg,
            "stats": stats,
        })
    except Exception as e:
        return JsonResponse({"error": f"خطا در خواندن و بازیابی فایل: {e}"}, status=400)


from django.contrib.auth import update_session_auth_hash


@require_POST
def password_login_view(request: HttpRequest) -> HttpResponse:
    """
    Authenticates existing users via email and password if enabled on their profile.
    Initial registration is strictly Google OAuth only.
    """
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    ident = request.POST.get("email", "").strip()
    password = request.POST.get("password", "")

    if not ident or not password:
        return render(request, "home.html", {
            "title": "Nightly Vocab | صفحه اصلی",
            "login_error": "لطفاً ایمیل و رمز عبور را وارد کنید.",
            "email_val": ident,
        })

    user = User.objects.filter(email__iexact=ident).first() or User.objects.filter(username__iexact=ident).first()

    if not user:
        return render(request, "home.html", {
            "title": "Nightly Vocab | صفحه اصلی",
            "login_error": "حساب کاربری با این ایمیل یافت نشد. ثبت‌نام اولیه در سامانه تنها از طریق حساب گوگل انجام می‌شود.",
            "email_val": ident,
        })

    profile = getattr(user, "profile", None)
    if not profile or not profile.password_login_enabled:
        return render(request, "home.html", {
            "title": "Nightly Vocab | صفحه اصلی",
            "login_error": "امکان ورود با رمز عبور برای این حساب فعال نشده است. لطفاً ابتدا با حساب گوگل وارد شوید و در تنظیمات، ورود با رمز عبور را فعال کنید.",
            "email_val": ident,
        })

    if not user.check_password(password):
        return render(request, "home.html", {
            "title": "Nightly Vocab | صفحه اصلی",
            "login_error": "رمز عبور وارد شده نادرست است.",
            "email_val": ident,
        })

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("accounts:dashboard")


@login_required
@require_POST
def set_password_api(request: HttpRequest) -> JsonResponse:
    """
    Allows an authenticated user to set a local password and enable/disable password-based login.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    enabled = bool(data.get("enabled", False))
    password = (data.get("password") or data.get("new_password") or "").strip()
    password_confirm = (data.get("password_confirm") or data.get("confirm_password") or "").strip()

    profile = request.user.profile

    if enabled:
        if password:
            if len(password) < 6:
                return JsonResponse({"error": "رمز عبور باید حداقل ۶ کاراکتر باشد."}, status=400)
            if password != password_confirm:
                return JsonResponse({"error": "تکرار رمز عبور با رمز عبور جدید یکسان نیست."}, status=400)
            request.user.set_password(password)
            request.user.save()
            update_session_auth_hash(request, request.user)
        elif not request.user.has_usable_password():
            return JsonResponse({"error": "برای فعال‌سازی ورود با رمز عبور، لطفاً ابتدا یک رمز عبور تعیین کنید."}, status=400)

        profile.password_login_enabled = True
        profile.save(update_fields=["password_login_enabled"])
        return JsonResponse({
            "success": True,
            "message": "تنظیمات ذخیره شد و ورود با رمز عبور فعال گردید.",
        })
    else:
        profile.password_login_enabled = False
        profile.save(update_fields=["password_login_enabled"])
        return JsonResponse({
            "success": True,
            "message": "ورود با رمز عبور غیرفعال شد. اکنون ورود فقط از طریق حساب گوگل امکان‌پذیر است.",
        })


