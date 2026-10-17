"""Super-admin management panel views and APIs (Patch B.3, B.4, B.5)."""
import csv
import functools
import json
import secrets
from datetime import date, timedelta
from typing import Any, Dict, List

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Profile
from apps.cards.models import WordCard
from apps.services.ai.gemini import GeminiProvider
from apps.services.models import (
    AdminAuditLog,
    AiUsage,
    SiteConfig,
    TelegramUsage,
    UserApiKey,
    UserControl,
)
from apps.telegram_bot.client import TelegramClient

User = get_user_model()


def admin_required(view_func):
    """
    Decorator requiring admin status (is_staff or is_superuser).
    Raises Http404 for non-admins (including regular logged-in users and anonymous).
    """
    @functools.wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
            raise Http404("صفحه مورد نظر یافت نشد.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


# Backward compatibility alias
superuser_required = admin_required


# =====================================================================
# 1. Management Dashboard (/manage/)
# =====================================================================
@superuser_required
@require_GET
def manage_dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    Super-admin dashboard:
    - Shared-key calls today and this month vs global caps (progress bars)
    - Active users (last 7 days) and total users / cards
    - Top 10 users by shared-key calls this month
    - Bot status (connected users, messages today)
    - Recent audit log entries
    """
    today = timezone.localdate()
    month_start = today.replace(day=1)
    config = SiteConfig.get()

    # Shared calls today vs daily cap
    today_shared_calls = (
        AiUsage.objects.filter(date=today, source="shared").aggregate(sum=Sum("calls"))["sum"] or 0
    )
    daily_cap = config.global_ai_daily_cap
    daily_pct = min(100, int((today_shared_calls / daily_cap) * 100)) if daily_cap > 0 else 0

    # Shared calls this month vs monthly cap
    month_shared_calls = (
        AiUsage.objects.filter(date__gte=month_start, date__lte=today, source="shared")
        .aggregate(sum=Sum("calls"))["sum"]
        or 0
    )
    monthly_cap = config.global_ai_monthly_cap
    monthly_pct = min(100, int((month_shared_calls / monthly_cap) * 100)) if monthly_cap > 0 else 0

    # User & card counts
    total_users = User.objects.count()
    seven_days_ago = today - timedelta(days=7)
    active_users_7d = Profile.objects.filter(last_active_date__gte=seven_days_ago).count()
    total_cards = WordCard.objects.count()

    # Top 10 users by shared-key calls this month
    top_users_qs = (
        AiUsage.objects.filter(date__gte=month_start, date__lte=today, source="shared")
        .values("user_id", "user__email", "user__username")
        .annotate(total_calls=Sum("calls"), total_tokens=Sum("input_tokens") + Sum("output_tokens"))
        .order_by("-total_calls")[:10]
    )

    # Telegram bot metrics
    tg_connected_users = Profile.objects.filter(telegram_chat_id__isnull=False).count()
    tg_messages_today = (
        TelegramUsage.objects.filter(date=today).aggregate(sum=Sum("messages_sent"))["sum"] or 0
    )

    # Recent audit logs
    recent_logs = AdminAuditLog.objects.select_related("admin", "target_user").order_by("-created_at")[:10]

    return render(
        request,
        "manage/dashboard.html",
        {
            "config": config,
            "today_shared_calls": today_shared_calls,
            "daily_cap": daily_cap,
            "daily_pct": daily_pct,
            "month_shared_calls": month_shared_calls,
            "monthly_cap": monthly_cap,
            "monthly_pct": monthly_pct,
            "total_users": total_users,
            "active_users_7d": active_users_7d,
            "total_cards": total_cards,
            "top_users": top_users_qs,
            "tg_connected_users": tg_connected_users,
            "tg_messages_today": tg_messages_today,
            "recent_logs": recent_logs,
            "title": "داشبورد مدیریت سامانه | LexiContext",
        },
    )


# =====================================================================
# 2. Management Settings (/manage/settings/)
# =====================================================================
@superuser_required
def manage_settings_view(request: HttpRequest) -> HttpResponse:
    """
    Super-admin settings forms:
    - AI configuration (provider, model, shared key with masked display + replace + test button, master switch)
    - Telegram configuration (token masked + replace, username, enabled switch, test webhook button)
    - Defaults & global caps
    - Access & allowed emails
    """
    config = SiteConfig.get()
    success_msg = None
    error_msg = None

    if request.method == "POST":
        section = request.POST.get("section", "")
        changed_fields = {}

        try:
            if section == "ai":
                config.ai_provider = request.POST.get("ai_provider", config.ai_provider).strip()
                config.ai_model = request.POST.get("ai_model", config.ai_model).strip()
                config.ai_master_switch = "ai_master_switch" in request.POST

                new_key = request.POST.get("new_shared_ai_key", "").strip()
                if new_key:
                    config.set_shared_ai_key(new_key)
                    changed_fields["shared_ai_key"] = f"••••{new_key[-4:]}"

                changed_fields.update({
                    "ai_provider": config.ai_provider,
                    "ai_model": config.ai_model,
                    "ai_master_switch": config.ai_master_switch,
                })
                config.save()
                success_msg = "تنظیمات هوش مصنوعی با موفقیت به‌روزرسانی شد."

            elif section == "telegram":
                config.tg_bot_username = request.POST.get("tg_bot_username", config.tg_bot_username).strip()
                config.tg_enabled = "tg_enabled" in request.POST
                config.tg_rate_limit_type = request.POST.get("tg_rate_limit_type", config.tg_rate_limit_type)
                try:
                    config.tg_user_rate_limit = max(0, int(request.POST.get("tg_user_rate_limit", config.tg_user_rate_limit)))
                except (ValueError, TypeError):
                    pass

                config.tg_force_join_enabled = "tg_force_join_enabled" in request.POST

                channel_ids = request.POST.getlist("force_channel_id[]")
                channel_titles = request.POST.getlist("force_channel_title[]")
                channel_links = request.POST.getlist("force_channel_link[]")

                targets = []
                for i in range(max(len(channel_ids), len(channel_titles), len(channel_links))):
                    cid = channel_ids[i].strip() if i < len(channel_ids) else ""
                    ctitle = channel_titles[i].strip() if i < len(channel_titles) else ""
                    clink = channel_links[i].strip() if i < len(channel_links) else ""
                    if cid:
                        targets.append({
                            "channel": cid,
                            "title": ctitle or cid,
                            "link": clink,
                        })

                config.tg_force_join_targets = targets
                if targets:
                    config.tg_force_join_channel = targets[0]["channel"]
                    config.tg_force_join_link = targets[0]["link"]
                else:
                    config.tg_force_join_channel = ""
                    config.tg_force_join_link = ""

                new_token = request.POST.get("new_tg_bot_token", "").strip()
                if new_token:
                    config.set_tg_bot_token(new_token)
                    changed_fields["tg_bot_token"] = f"••••{new_token[-4:]}"

                changed_fields.update({
                    "tg_bot_username": config.tg_bot_username,
                    "tg_enabled": config.tg_enabled,
                    "tg_rate_limit_type": config.tg_rate_limit_type,
                    "tg_user_rate_limit": config.tg_user_rate_limit,
                    "tg_force_join_enabled": config.tg_force_join_enabled,
                    "tg_force_join_targets_count": len(targets),
                })
                config.save()
                success_msg = "تنظیمات ربات تلگرام با موفقیت به‌روزرسانی شد."

            elif section == "caps":
                config.default_ai_daily_limit = int(request.POST.get("default_ai_daily_limit", config.default_ai_daily_limit))
                config.default_ai_monthly_limit = int(request.POST.get("default_ai_monthly_limit", config.default_ai_monthly_limit))
                config.default_max_targets_per_call = int(request.POST.get("default_max_targets_per_call", config.default_max_targets_per_call))
                config.global_ai_daily_cap = int(request.POST.get("global_ai_daily_cap", config.global_ai_daily_cap))
                config.global_ai_monthly_cap = int(request.POST.get("global_ai_monthly_cap", config.global_ai_monthly_cap))
                config.default_ai_access = request.POST.get("default_ai_access", config.default_ai_access)
                config.default_telegram_access = request.POST.get("default_telegram_access", config.default_telegram_access)

                changed_fields.update({
                    "default_ai_daily_limit": config.default_ai_daily_limit,
                    "default_ai_monthly_limit": config.default_ai_monthly_limit,
                    "global_ai_daily_cap": config.global_ai_daily_cap,
                    "global_ai_monthly_cap": config.global_ai_monthly_cap,
                    "default_ai_access": config.default_ai_access,
                })
                config.save()
                success_msg = "سقف‌ها و سیاست‌های پیش‌فرض ذخیره شدند."

            elif section == "access":
                config.signups_open = "signups_open" in request.POST
                config.allowed_emails = request.POST.get("allowed_emails", "").strip()

                changed_fields.update({
                    "signups_open": config.signups_open,
                    "allowed_emails_count": len([e for e in config.allowed_emails.splitlines() if e.strip()]),
                })
                config.save()
                success_msg = "تنظیمات دسترسی و لیست مجاز ذخیره شدند."

            elif section == "backup":
                config.backup_enabled = "backup_enabled" in request.POST
                config.backup_schedule = request.POST.get("backup_schedule", "daily")
                tg_chat_raw = request.POST.get("backup_telegram_chat_id", "").strip()
                config.backup_telegram_chat_id = int(tg_chat_raw) if tg_chat_raw.isdigit() else None
                config.save()
                changed_fields.update({
                    "backup_enabled": config.backup_enabled,
                    "backup_schedule": config.backup_schedule,
                    "backup_telegram_chat_id": config.backup_telegram_chat_id,
                })
                success_msg = "تنظیمات پشتیبان‌گیری خودکار تلگرام با موفقیت ذخیره شد."

            elif section == "google":
                config.google_client_id = request.POST.get("google_client_id", "").strip()
                config.google_oauth_enabled = "google_oauth_enabled" in request.POST
                config.google_site_verification = request.POST.get("google_site_verification", "").strip()

                new_sec = request.POST.get("new_google_client_secret", "").strip()
                if new_sec:
                    config.set_google_client_secret(new_sec)
                    changed_fields["google_client_secret"] = f"••••{new_sec[-4:]}"

                changed_fields.update({
                    "google_client_id": config.google_client_id,
                    "google_oauth_enabled": config.google_oauth_enabled,
                    "google_site_verification": config.google_site_verification,
                })
                config.save()
                config.sync_google_social_app()
                success_msg = "تنظیمات احراز هویت گوگل و سرچ کنسول با موفقیت ذخیره و همگام‌سازی شد."

            # Log audit entry
            AdminAuditLog.objects.create(
                admin=request.user,
                action=f"update_settings_{section}",
                details=changed_fields,
            )

        except Exception as exc:
            error_msg = f"خطا در ذخیره تنظیمات: {exc}"

    return render(
        request,
        "manage/settings.html",
        {
            "config": config,
            "success_msg": success_msg,
            "error_msg": error_msg,
            "title": "تنظیمات سراسری سامانه | مدیریت",
        },
    )


# =====================================================================
# 3. Users Table & CSV Export (/manage/users/)
# =====================================================================
@superuser_required
@require_GET
def manage_users_view(request: HttpRequest) -> HttpResponse:
    """
    Users management table:
    - Search by email / username
    - Filter by status (blocked, ai_disabled, own_only, active)
    - Sort by usage, joined, cards count
    - Pagination
    """
    today = timezone.localdate()
    month_start = today.replace(day=1)

    users_qs = User.objects.select_related("profile", "control").order_by("-date_joined")

    # Search
    q = request.GET.get("q", "").strip()
    if q:
        users_qs = users_qs.filter(Q(email__icontains=q) | Q(username__icontains=q))

    # Filter by status
    status_filter = request.GET.get("status", "").strip()
    if status_filter == "blocked":
        users_qs = users_qs.filter(control__is_blocked=True)
    elif status_filter == "ai_disabled":
        users_qs = users_qs.filter(control__ai_access="disabled")
    elif status_filter == "own_only":
        users_qs = users_qs.filter(control__ai_access="own_only")

    # Sort
    sort_by = request.GET.get("sort", "joined_desc")
    if sort_by == "joined_asc":
        users_qs = users_qs.order_by("date_joined")
    elif sort_by == "last_active":
        users_qs = users_qs.order_by("-profile__last_active_date", "-date_joined")
    else:
        users_qs = users_qs.order_by("-date_joined")

    paginator = Paginator(users_qs, 25)
    page_number = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    # Annotate row data (cards count, usage, tg status)
    user_rows: List[Dict[str, Any]] = []
    user_ids = [u.id for u in page_obj]

    # Pre-fetch card counts
    cards_counts = dict(
        WordCard.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )

    # Pre-fetch today's shared calls
    today_usage = dict(
        AiUsage.objects.filter(user_id__in=user_ids, date=today, source="shared")
        .values("user_id")
        .annotate(s=Sum("calls"))
        .values_list("user_id", "s")
    )

    # Pre-fetch month's shared calls
    month_usage = dict(
        AiUsage.objects.filter(user_id__in=user_ids, date__gte=month_start, date__lte=today, source="shared")
        .values("user_id")
        .annotate(s=Sum("calls"))
        .values_list("user_id", "s")
    )

    for u in page_obj:
        control = getattr(u, "control", None)
        profile = getattr(u, "profile", None)
        has_own_key = UserApiKey.objects.filter(user=u, enabled=True).exists()

        user_rows.append({
            "user": u,
            "profile": profile,
            "control": control,
            "cards_count": cards_counts.get(u.id, 0),
            "today_shared": today_usage.get(u.id, 0),
            "month_shared": month_usage.get(u.id, 0),
            "has_own_key": has_own_key,
            "telegram_connected": bool(profile and profile.telegram_chat_id),
            "is_blocked": bool(control and control.is_blocked),
            "ai_access": control.ai_access if control else "inherit",
        })

    return render(
        request,
        "manage/users.html",
        {
            "user_rows": user_rows,
            "page_obj": page_obj,
            "q": q,
            "status_filter": status_filter,
            "sort_by": sort_by,
            "total_users_count": User.objects.count(),
            "title": "مدیریت کاربران | پنل مدیریت",
        },
    )


@superuser_required
@require_GET
def manage_users_export_csv(request: HttpRequest) -> HttpResponse:
    """Exports user statistics as UTF-8 CSV with BOM for Excel compatibility."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="lexicontext_users.csv"'
    response.write("\ufeff")  # UTF-8 BOM

    writer = csv.writer(response)
    writer.writerow([
        "شناسه",
        "ایمیل",
        "نام کاربری",
        "تاریخ عضویت",
        "آخرین فعالیت",
        "تعداد کارت‌ها",
        "دسترسی هوش مصنوعی",
        "وضعیت مسدودی",
        "تلگرام متصل",
    ])

    users = User.objects.select_related("profile", "control").order_by("id")
    for u in users:
        control = getattr(u, "control", None)
        profile = getattr(u, "profile", None)
        cards_count = WordCard.objects.filter(user=u).count()
        writer.writerow([
            u.id,
            u.email or "",
            u.username,
            u.date_joined.strftime("%Y-%m-%d"),
            profile.last_active_date.strftime("%Y-%m-%d") if profile and profile.last_active_date else "—",
            cards_count,
            control.ai_access if control else "inherit",
            "بله" if control and control.is_blocked else "خیر",
            "بله" if profile and profile.telegram_chat_id else "خیر",
        ])

    return response


# =====================================================================
# 4. User Detail & Overrides (/manage/users/<id>/)
# =====================================================================
@superuser_required
def manage_user_detail_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """
    User detail page:
    - Last 30 days usage table (date, shared, own, failed, tokens, tg messages)
    - Per-user overrides form (ai_access, daily/monthly limits, telegram_access, blocked, note)
    - Writes AdminAuditLog on every change
    - Never exposes user cards or plaintext keys
    """
    target_user = get_object_or_404(User, pk=user_id)
    profile, _ = Profile.objects.get_or_create(user=target_user)
    control, _ = UserControl.objects.get_or_create(user=target_user)
    config = SiteConfig.get()
    success_msg = None
    error_msg = None

    if request.method == "POST":
        action = request.POST.get("action", "save_overrides")

        if action == "save_overrides":
            try:
                ai_access = request.POST.get("ai_access", control.ai_access)
                if ai_access in ("inherit", "shared", "own_only", "disabled"):
                    control.ai_access = ai_access

                raw_daily = request.POST.get("ai_daily_limit", "").strip()
                control.ai_daily_limit = int(raw_daily) if raw_daily.isdigit() else None

                raw_monthly = request.POST.get("ai_monthly_limit", "").strip()
                control.ai_monthly_limit = int(raw_monthly) if raw_monthly.isdigit() else None

                raw_max_targets = request.POST.get("max_targets_per_call", "").strip()
                control.max_targets_per_call = int(raw_max_targets) if raw_max_targets.isdigit() else None

                tg_access = request.POST.get("telegram_access", control.telegram_access)
                if tg_access in ("inherit", "allowed", "blocked"):
                    control.telegram_access = tg_access

                control.is_blocked = "is_blocked" in request.POST
                control.admin_note = request.POST.get("admin_note", "").strip()
                control.save()

                AdminAuditLog.objects.create(
                    admin=request.user,
                    target_user=target_user,
                    action="update_user_overrides",
                    details={
                        "ai_access": control.ai_access,
                        "ai_daily_limit": control.ai_daily_limit,
                        "ai_monthly_limit": control.ai_monthly_limit,
                        "is_blocked": control.is_blocked,
                        "telegram_access": control.telegram_access,
                    },
                )
                success_msg = "تنظیمات اختصاصی کاربر با موفقیت ذخیره شد."
            except Exception as exc:
                error_msg = f"خطا در ذخیره تغییرات: {exc}"

    # 30-day usage history table
    today = timezone.localdate()
    start_date = today - timedelta(days=29)

    ai_logs = AiUsage.objects.filter(
        user=target_user,
        date__gte=start_date,
        date__lte=today,
    )
    ai_map: Dict[date, Dict[str, Any]] = {}
    for entry in ai_logs:
        if entry.date not in ai_map:
            ai_map[entry.date] = {"shared": 0, "own": 0, "failed": 0, "tokens": 0}
        if entry.source == "shared":
            ai_map[entry.date]["shared"] += entry.calls
        else:
            ai_map[entry.date]["own"] += entry.calls
        ai_map[entry.date]["failed"] += entry.failed_calls
        ai_map[entry.date]["tokens"] += entry.input_tokens + entry.output_tokens

    tg_logs = dict(
        TelegramUsage.objects.filter(user=target_user, date__gte=start_date, date__lte=today)
        .values("date")
        .annotate(s=Sum("messages_sent"))
        .values_list("date", "s")
    )

    usage_history: List[Dict[str, Any]] = []
    for offset in range(30):
        d = today - timedelta(days=offset)
        a_data = ai_map.get(d, {"shared": 0, "own": 0, "failed": 0, "tokens": 0})
        usage_history.append({
            "date": d,
            "shared_calls": a_data["shared"],
            "own_calls": a_data["own"],
            "failed_calls": a_data["failed"],
            "tokens": a_data["tokens"],
            "tg_messages": tg_logs.get(d, 0),
        })

    # BYOK status (masked only)
    user_key = UserApiKey.objects.filter(user=target_user, provider=config.ai_provider).first()

    # Effective limit calculations
    effective_daily = control.ai_daily_limit if control.ai_daily_limit is not None else config.default_ai_daily_limit
    effective_monthly = control.ai_monthly_limit if control.ai_monthly_limit is not None else config.default_ai_monthly_limit
    effective_access = control.ai_access if control.ai_access != "inherit" else config.default_ai_access

    return render(
        request,
        "manage/user_detail.html",
        {
            "target_user": target_user,
            "profile": profile,
            "control": control,
            "config": config,
            "user_key": user_key,
            "usage_history": usage_history,
            "effective_daily": effective_daily,
            "effective_monthly": effective_monthly,
            "effective_access": effective_access,
            "success_msg": success_msg,
            "error_msg": error_msg,
            "title": f"کاربر {target_user.email or target_user.username} | مدیریت",
        },
    )


# =====================================================================
# 5. Quick Actions & Test APIs (Superuser only)
# =====================================================================
@superuser_required
@require_POST
def manage_quick_action_api(request: HttpRequest, user_id: int) -> JsonResponse:
    """Handles quick management actions on a user."""
    target_user = get_object_or_404(User, pk=user_id)
    control, _ = UserControl.objects.get_or_create(user=target_user)

    try:
        data = json.loads(request.body)
        action = data.get("action", "")
    except Exception:
        return JsonResponse({"error": "فرمت داده‌ها نامعتبر است."}, status=400)

    if action == "disable_ai":
        control.ai_access = "disabled"
        control.save(update_fields=["ai_access"])
    elif action == "require_own_key":
        control.ai_access = "own_only"
        control.save(update_fields=["ai_access"])
    elif action == "block_telegram":
        control.telegram_access = "blocked"
        control.save(update_fields=["telegram_access"])
    elif action == "toggle_block_user":
        control.is_blocked = not control.is_blocked
        control.save(update_fields=["is_blocked"])
    elif action == "reset_today_usage":
        today = timezone.localdate()
        AiUsage.objects.filter(user=target_user, date=today).update(calls=0)
    elif action == "toggle_admin_role":
        if not request.user.is_superuser:
            return JsonResponse({"error": "فقط سوپرادمین مجاز به تغییر نقش ادمین است."}, status=403)
        if target_user == request.user:
            return JsonResponse({"error": "نمی‌توانید نقش کاربری خود را تغییر دهید."}, status=400)
        target_user.is_staff = not target_user.is_staff
        target_user.save(update_fields=["is_staff"])
    else:
        return JsonResponse({"error": "عملیات نامعتبر است."}, status=400)

    AdminAuditLog.objects.create(
        admin=request.user,
        target_user=target_user,
        action=f"quick_action_{action}",
        details={"status": "executed"},
    )

    return JsonResponse({"success": True, "action": action})


@superuser_required
@require_POST
def manage_test_ai_key_api(request: HttpRequest) -> JsonResponse:
    """Tests the shared Gemini key or a candidate key from the panel."""
    try:
        data = json.loads(request.body)
        key_to_test = data.get("api_key", "").strip()
    except Exception:
        key_to_test = ""

    config = SiteConfig.get()
    if not key_to_test:
        key_to_test = config.get_shared_ai_key()

    if not key_to_test:
        return JsonResponse({"error": "کلیدی برای آزمایش مشخص نشده است."}, status=400)

    is_valid, err = GeminiProvider.test_api_key(key_to_test)
    if is_valid:
        return JsonResponse({"success": True, "message": "اتصال به Google Gemini با موفقیت برقرار شد."})
    return JsonResponse({"error": f"خطا در تأیید کلید: {err}"}, status=400)


@superuser_required
@require_POST
def manage_test_telegram_api(request: HttpRequest) -> JsonResponse:
    """Tests the Telegram bot token and automatically re-registers the webhook."""
    config = SiteConfig.get()
    token = config.get_tg_bot_token()
    if not token:
        return JsonResponse({"error": "توکن تلگرام تنظیم نشده است."}, status=400)

    try:
        client = TelegramClient(token=token)
        me = client.get_me()
        bot_username = me.get("username", "")

        secret = config.get_tg_webhook_secret() or secrets.token_urlsafe(32)
        site_url = getattr(settings, "SITE_URL", "http://localhost:8000")
        webhook_url = f"{site_url.rstrip('/')}/telegram/webhook/"

        client.set_webhook(webhook_url=webhook_url, secret_token=secret)

        config.tg_bot_username = bot_username
        config.save(update_fields=["tg_bot_username"])

        return JsonResponse({
            "success": True,
            "bot_username": bot_username,
            "webhook_url": webhook_url,
        })
    except Exception as exc:
        return JsonResponse({"error": f"خطا در برقراری ارتباط با تلگرام: {exc}"}, status=400)


# =====================================================================
# 6. System Backup & Restore Views (Admin Only)
# =====================================================================

@admin_required
@require_GET
def manage_download_backup_view(request: HttpRequest) -> HttpResponse:
    """Generates and downloads full system backup as a JSON file."""
    from .backup_service import generate_system_backup_bytes
    backup_bytes = generate_system_backup_bytes()
    now_str = timezone.now().strftime("%Y-%m-%d_%H%M")
    response = HttpResponse(backup_bytes, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="lexicontext_backup_{now_str}.json"'
    return response


@admin_required
@require_POST
def manage_send_backup_telegram_api(request: HttpRequest) -> JsonResponse:
    """Manually triggers immediate transmission of system backup to admin Telegram."""
    from .backup_service import send_system_backup_to_telegram
    try:
        data = json.loads(request.body) if request.body else {}
        chat_id = data.get("chat_id")
    except Exception:
        chat_id = None

    try:
        result = send_system_backup_to_telegram(target_chat_id=chat_id)
        return JsonResponse({"success": True, "message": "فایل پشتیبان با موفقیت به تلگرام ادمین ارسال شد.", "result": result})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@admin_required
@require_POST
def manage_restore_backup_view(request: HttpRequest) -> HttpResponse:
    """Uploads and restores system from a JSON backup file."""
    from .backup_service import restore_system_backup
    backup_file = request.FILES.get("backup_file")
    config = SiteConfig.get()
    if not backup_file:
        return render(request, "manage/settings.html", {
            "config": config,
            "error_msg": "لطفاً فایل پشتیبان (.json) را انتخاب کنید.",
            "title": "تنظیمات سراسری سامانه | مدیریت",
        })

    try:
        content = backup_file.read().decode("utf-8")
        data = json.loads(content)
        stats = restore_system_backup(data)
        success_msg = f"بازیابی با موفقیت انجام شد: {stats['users']} کاربر، {stats['texts']} متن، و {stats['cards']} کارت واژگان بازگردانی شدند."
        return render(request, "manage/settings.html", {
            "config": config,
            "success_msg": success_msg,
            "title": "تنظیمات سراسری سامانه | مدیریت",
        })
    except Exception as e:
        return render(request, "manage/settings.html", {
            "config": config,
            "error_msg": f"خطا در بازیابی فایل: {e}",
            "title": "تنظیمات سراسری سامانه | مدیریت",
        })

