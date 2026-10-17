#!/usr/bin/env bash
# ==============================================================================
# Nightly Vocab / LexiContext — Server Management CLI (vocab)
# Inspired by Sanaei x-ui management CLI
# ==============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/nightly-vocab"
SERVICE_NAME="nightly-vocab"
ENV_FILE="${INSTALL_DIR}/.env"
PYTHON_BIN="${INSTALL_DIR}/venv/bin/python"
PIP_BIN="${INSTALL_DIR}/venv/bin/pip"

# Ensure running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[!] این اسکریپت باید با دسترسی root اجرا شود.${NC}"
        echo -e "لطفاً با دستور ${YELLOW}sudo vocab${NC} اجرا کنید."
        exit 1
    fi
}

# Print Fancy Banner
show_banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    cat << "EOF"
  _   _ _       _     _   _         __      __          _     
 | \ | (_)     | |   | | | |        \ \    / /         | |    
 |  \| |_  __ _| |__ | |_| |_   _    \ \  / /__   ___  | |__  
 | . ` | |/ _` | '_ \| __| | | | |    \ \/ / _ \ / __| | '_ \ 
 | |\  | | (_| | | | | |_| | |_| |     \  / (_) | (__  | |_) |
 |_| \_|_|\__, |_| |_|\__|_|\__, |      \/ \___/ \___| |_.__/ 
           __/ |             __/ |                            
          |___/             |___/                             
EOF
    echo -e "${PURPLE}  ======================================================${NC}"
    echo -e "${YELLOW}  Nightly Vocab / LexiContext — ابزار مدیریت سرور (CLI)${NC}"
    echo -e "${PURPLE}  ======================================================${NC}"
    echo ""
}

# Check Service Status
check_status() {
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo -e "  وضعیت سرویس: ${GREEN}● فعال و در حال اجرا (Active / Running)${NC}"
    else
        echo -e "  وضعیت سرویس: ${RED}○ متوقف شده (Inactive / Stopped)${NC}"
    fi

    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        echo -e "  اجرای خودکار: ${GREEN}فعال (Auto-start enabled)${NC}"
    else
        echo -e "  اجرای خودکار: ${YELLOW}غیرفعال (Disabled)${NC}"
    fi

    if [[ -f "${ENV_FILE}" ]]; then
        local domain=$(grep -E "^DOMAIN=" "${ENV_FILE}" | cut -d '=' -f2- | tr -d ' "' || echo "تنظیم نشده")
        echo -e "  دامنه سامانه: ${CYAN}https://${domain}${NC}"
    fi
    echo ""
}

# Start Service
start_service() {
    echo -e "${YELLOW}[*] در حال شروع سرویس...${NC}"
    systemctl start "${SERVICE_NAME}"
    sleep 2
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo -e "${GREEN}[✓] سرویس با موفقیت اجرا شد.${NC}"
    else
        echo -e "${RED}[!] خطا در اجرای سرویس. لاگ‌ها را بررسی کنید:${NC}"
        journalctl -u "${SERVICE_NAME}" -n 20 --no-pager
    fi
}

# Stop Service
stop_service() {
    echo -e "${YELLOW}[*] در حال توقف سرویس...${NC}"
    systemctl stop "${SERVICE_NAME}"
    echo -e "${GREEN}[✓] سرویس متوقف شد.${NC}"
}

# Restart Service
restart_service() {
    echo -e "${YELLOW}[*] در حال راه‌اندازی مجدد سرویس...${NC}"
    systemctl restart "${SERVICE_NAME}"
    sleep 2
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo -e "${GREEN}[✓] سرویس با موفقیت راه‌اندازی مجدد شد.${NC}"
    else
        echo -e "${RED}[!] خطا در راه‌اندازی مجدد سرویس.${NC}"
        journalctl -u "${SERVICE_NAME}" -n 20 --no-pager
    fi
}

# View Live Logs
view_logs() {
    echo -e "${CYAN}[*] در حال نمایش لاگ‌های زنده (برای خروج Ctrl+C را بزنید)...${NC}"
    sleep 1
    journalctl -u "${SERVICE_NAME}" -f -n 50
}

# Update from GitHub
update_app() {
    echo -e "${CYAN}${BOLD}[*] در حال بررسی و دریافت آخرین نسخه از گیت‌هاب...${NC}"
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
        echo -e "${RED}[!] پوشه نصب به گیت متصل نیست (${INSTALL_DIR}).${NC}"
        return 1
    fi

    cd "${INSTALL_DIR}"
    
    # Save current changes if any
    git stash >/dev/null 2>&1 || true
    
    # Pull latest changes
    echo -e "${YELLOW}[1/4] دریافت فایل‌های جدید (git pull)...${NC}"
    git pull origin main || git pull origin master

    # Update dependencies
    echo -e "${YELLOW}[2/4] به‌روزرسانی کتابخانه‌های پایتون...${NC}"
    ${PIP_BIN} install -q -r requirements.txt

    # Run migrations
    echo -e "${YELLOW}[3/4] اعمال تغییرات دیتابیس (Migrations)...${NC}"
    ${PYTHON_BIN} manage.py migrate --noinput --settings=config.settings.prod

    # Collect static files
    echo -e "${YELLOW}[4/4] به‌روزرسانی فایل‌های استاتیک...${NC}"
    ${PYTHON_BIN} manage.py collectstatic --noinput --settings=config.settings.prod

    # Restart service
    echo -e "${YELLOW}[*] راه‌اندازی مجدد سرویس...${NC}"
    systemctl restart "${SERVICE_NAME}"
    
    echo -e "${GREEN}${BOLD}[✓] به‌روزرسانی با موفقیت تکمیل شد! آخرین نسخه در حال اجراست.${NC}"
}

# Change Domain & SSL
configure_ssl() {
    echo -e "${CYAN}${BOLD}[*] تنظیم دامنه و گواهی رایگان SSL (Let's Encrypt)...${NC}"
    read -rp "دامنه جدید خود را وارد کنید (مثال: vocab.domain.com): " NEW_DOMAIN
    NEW_DOMAIN=$(echo "${NEW_DOMAIN}" | tr -d ' ' | tr '[:upper:]' '[:lower:]')

    if [[ -z "${NEW_DOMAIN}" ]]; then
        echo -e "${RED}[!] دامنه نمی‌تواند خالی باشد.${NC}"
        return 1
    fi

    read -rp "یک آدرس ایمیل معتبر برای گواهی SSL وارد کنید: " SSL_EMAIL
    if [[ -z "${SSL_EMAIL}" ]]; then
        SSL_EMAIL="admin@${NEW_DOMAIN}"
    fi

    echo -e "${YELLOW}[*] دریافت گواهی SSL برای ${NEW_DOMAIN}...${NC}"
    systemctl stop nginx || true
    certbot certonly --standalone -d "${NEW_DOMAIN}" --non-interactive --agree-tos --email "${SSL_EMAIL}" || {
        echo -e "${RED}[!] خطا در دریافت گواهی SSL. لطفاً اطمینان حاصل کنید رکورد A دامنه به این سرور متصل است و پورت ۸۰ باز است.${NC}"
        systemctl start nginx || true
        return 1
    }

    # Update .env
    sed -i "s|^DOMAIN=.*|DOMAIN=${NEW_DOMAIN}|" "${ENV_FILE}"
    sed -i "s|^SITE_URL=.*|SITE_URL=https://${NEW_DOMAIN}|" "${ENV_FILE}"
    sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=${NEW_DOMAIN},127.0.0.1,localhost|" "${ENV_FILE}"
    sed -i "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://${NEW_DOMAIN}|" "${ENV_FILE}"

    # Update Nginx config
    cat > "/etc/nginx/sites-available/nightly-vocab" << EOF
server {
    listen 80;
    server_name ${NEW_DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${NEW_DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${NEW_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${NEW_DOMAIN}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    client_max_body_size 25M;

    location /static/ {
        alias ${INSTALL_DIR}/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    location /media/ {
        alias ${INSTALL_DIR}/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
    }
}
EOF
    ln -sf "/etc/nginx/sites-available/nightly-vocab" "/etc/nginx/sites-enabled/nightly-vocab"
    nginx -t && systemctl restart nginx
    systemctl restart "${SERVICE_NAME}"
    echo -e "${GREEN}[✓] دامنه با موفقیت تغییر کرد و گواهی SSL نصب شد: https://${NEW_DOMAIN}${NC}"
}

# Change AI and Bot Secrets
configure_secrets() {
    echo -e "${CYAN}${BOLD}[*] تنظیم توکن‌ها و کلیدهای سامانه${NC}"
    echo -e "${YELLOW}(برای دست‌نخورده ماندن هر مقدار، فقط Enter بزنید)${NC}\n"

    read -rp "کلید هوش مصنوعی Google Gemini API Key: " NEW_GEMINI
    if [[ -n "${NEW_GEMINI}" ]]; then
        sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${NEW_GEMINI}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] کلید هوش مصنوعی ذخیره شد.${NC}"
    fi

    read -rp "توکن ربات تلگرام (Telegram Bot Token): " NEW_TG_TOKEN
    if [[ -n "${NEW_TG_TOKEN}" ]]; then
        sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${NEW_TG_TOKEN}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] توکن ربات تلگرام ذخیره شد.${NC}"
    fi

    read -rp "آیدی ربات تلگرام (با @، مثلا @NightlyVocabBot): " NEW_TG_USER
    if [[ -n "${NEW_TG_USER}" ]]; then
        [[ "${NEW_TG_USER}" != @* ]] && NEW_TG_USER="@${NEW_TG_USER}"
        sed -i "s|^TELEGRAM_BOT_USERNAME=.*|TELEGRAM_BOT_USERNAME=${NEW_TG_USER}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] آیدی ربات تلگرام ذخیره شد.${NC}"
    fi

    read -rp "شناسه Google OAuth Client ID: " NEW_G_ID
    if [[ -n "${NEW_G_ID}" ]]; then
        sed -i "s|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${NEW_G_ID}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] شناسه Google Client ID ذخیره شد.${NC}"
    fi

    read -rp "کلید رمز Google OAuth Client Secret: " NEW_G_SECRET
    if [[ -n "${NEW_G_SECRET}" ]]; then
        sed -i "s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${NEW_G_SECRET}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] کلید Google Client Secret ذخیره شد.${NC}"
    fi

    read -rp "کد تایید Google Search Console: " NEW_G_VERIFY
    if [[ -n "${NEW_G_VERIFY}" ]]; then
        if grep -q "^GOOGLE_SITE_VERIFICATION=" "${ENV_FILE}"; then
            sed -i "s|^GOOGLE_SITE_VERIFICATION=.*|GOOGLE_SITE_VERIFICATION=${NEW_G_VERIFY}|" "${ENV_FILE}"
        else
            echo "GOOGLE_SITE_VERIFICATION=${NEW_G_VERIFY}" >> "${ENV_FILE}"
        fi
        echo -e "${GREEN}[✓] کد تایید سرچ کنسول ذخیره شد.${NC}"
    fi

    # Sync to SiteConfig in database
    ${PYTHON_BIN} - << PYEOF
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()
from apps.services.models import SiteConfig
cfg = SiteConfig.get()
if "${NEW_AI_KEY}":
    cfg.set_shared_ai_key("${NEW_AI_KEY}")
if "${NEW_TG_TOKEN}":
    cfg.set_tg_bot_token("${NEW_TG_TOKEN}")
if "${NEW_TG_USER}":
    cfg.tg_bot_username = "${NEW_TG_USER}"
if "${NEW_G_ID}":
    cfg.google_client_id = "${NEW_G_ID}"
if "${NEW_G_SECRET}":
    cfg.set_google_client_secret("${NEW_G_SECRET}")
if "${NEW_G_VERIFY}":
    cfg.google_site_verification = "${NEW_G_VERIFY}"
cfg.save()
cfg.sync_google_social_app()
PYEOF

    systemctl restart "${SERVICE_NAME}"
    echo -e "\n${GREEN}[✓] تمامی تغییرات ذخیره، همگام‌سازی و سرویس بازنشانی شد.${NC}"
}

# Create Superuser / Change Admin Password
manage_admin() {
    echo -e "${CYAN}${BOLD}[*] مدیریت حساب مدیر ارشد (Superuser)${NC}"
    echo "1) ایجاد کاربر مدیر جدید"
    echo "2) تغییر رمز عبور کاربر مدیر موجود"
    read -rp "انتخاب شما [1-2]: " ADMIN_OPT

    cd "${INSTALL_DIR}"
    if [[ "${ADMIN_OPT}" == "1" ]]; then
        ${PYTHON_BIN} manage.py createsuperuser --settings=config.settings.prod
    elif [[ "${ADMIN_OPT}" == "2" ]]; then
        read -rp "نام کاربری یا ایمیل مدیر: " ADMIN_UNAME
        ${PYTHON_BIN} manage.py changepassword "${ADMIN_UNAME}" --settings=config.settings.prod
    fi
}

# Backup Database & Media
backup_data() {
    local BACKUP_DIR="/var/backups/nightly-vocab"
    mkdir -p "${BACKUP_DIR}"
    local TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    local BACKUP_FILE="${BACKUP_DIR}/vocab_backup_${TIMESTAMP}.tar.gz"

    echo -e "${YELLOW}[*] در حال تهیه نسخه پشتیبان کامل...${NC}"
    cd "${INSTALL_DIR}"
    tar -czf "${BACKUP_FILE}" \
        --exclude='venv' \
        --exclude='staticfiles' \
        --exclude='__pycache__' \
        .env db.sqlite3 media/ 2>/dev/null || true

    echo -e "${GREEN}[✓] نسخه پشتیبان در مسیر زیر ذخیره شد:${NC}"
    echo -e "    ${CYAN}${BACKUP_FILE}${NC}"
}

# Uninstall
uninstall_app() {
    echo -e "${RED}${BOLD}[!] هشدار: این عملیات سامانه Nightly Vocab و سرویس آن را حذف می‌کند.${NC}"
    read -rp "آیا مطمئن هستید؟ (y/N): " CONFIRM
    if [[ "${CONFIRM}" =~ ^[Yy]$ ]]; then
        systemctl stop "${SERVICE_NAME}" || true
        systemctl disable "${SERVICE_NAME}" || true
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        rm -f "/etc/nginx/sites-enabled/nightly-vocab"
        rm -f "/etc/nginx/sites-available/nightly-vocab"
        rm -f "/usr/local/bin/vocab"
        systemctl daemon-reload
        systemctl restart nginx || true
        echo -e "${YELLOW}آیا مایل به حذف کامل فایل‌ها و پایگاه‌داده در ${INSTALL_DIR} هستید؟ (y/N): ${NC}"
        read -rp "" DEL_DATA
        if [[ "${DEL_DATA}" =~ ^[Yy]$ ]]; then
            rm -rf "${INSTALL_DIR}"
            echo -e "${GREEN}[✓] فایل‌ها به طور کامل حذف شدند.${NC}"
        fi
        echo -e "${GREEN}[✓] سامانه با موفقیت غیرفعال و حذف گردید.${NC}"
        exit 0
    else
        echo -e "${YELLOW}[*] عملیات لغو شد.${NC}"
    fi
}

# Interactive CLI Menu
main_menu() {
    check_root
    while true; do
        show_banner
        check_status
        echo -e "${BOLD}منوی مدیریت:${NC}"
        echo -e "  ${GREEN}1)${NC} شروع سرویس (Start)"
        echo -e "  ${RED}2)${NC} توقف سرویس (Stop)"
        echo -e "  ${YELLOW}3)${NC} راه‌اندازی مجدد سرویس (Restart)"
        echo -e "  ${CYAN}4)${NC} مشاهده لاگ‌های زنده (Live Logs)"
        echo -e "  ${PURPLE}5)${NC} به‌روزرسانی سامانه از گیت‌هاب (Update from GitHub)"
        echo -e "  ${BLUE}6)${NC} تغییر دامنه و تمدید SSL (Domain & SSL)"
        echo -e "  ${YELLOW}7)${NC} تنظیم توکن ربات، هوش مصنوعی و گوگل (API Keys & Secrets)"
        echo -e "  ${CYAN}8)${NC} ایجاد یا تغییر رمز مدیر ارشد (Admin User)"
        echo -e "  ${GREEN}9)${NC} پشتیبان‌گیری از داده‌ها (Backup)"
        echo -e "  ${RED}10)${NC} حذف کامل سامانه (Uninstall)"
        echo -e "  ${BOLD}0)${NC} خروج (Exit)"
        echo ""
        read -rp "لطفاً یک گزینه را انتخاب کنید [0-10]: " CHOICE

        case "${CHOICE}" in
            1) start_service; read -rp "برای ادامه Enter بزنید..." ;;
            2) stop_service; read -rp "برای ادامه Enter بزنید..." ;;
            3) restart_service; read -rp "برای ادامه Enter بزنید..." ;;
            4) view_logs ;;
            5) update_app; read -rp "برای ادامه Enter بزنید..." ;;
            6) configure_ssl; read -rp "برای ادامه Enter بزنید..." ;;
            7) configure_secrets; read -rp "برای ادامه Enter بزنید..." ;;
            8) manage_admin; read -rp "برای ادامه Enter بزنید..." ;;
            9) backup_data; read -rp "برای ادامه Enter بزنید..." ;;
            10) uninstall_app ;;
            0) echo -e "${GREEN}روز خوبی داشته باشید!${NC}"; exit 0 ;;
            *) echo -e "${RED}[!] گزینه نامعتبر است.${NC}"; sleep 1 ;;
        esac
    done
}

# Direct subcommands support (e.g. vocab restart, vocab update)
if [[ $# -gt 0 ]]; then
    check_root
    case "$1" in
        start) start_service ;;
        stop) stop_service ;;
        restart) restart_service ;;
        status) check_status ;;
        logs|log) view_logs ;;
        update) update_app ;;
        ssl) configure_ssl ;;
        config|secrets) configure_secrets ;;
        backup) backup_data ;;
        admin|user) manage_admin ;;
        uninstall) uninstall_app ;;
        *) echo "دستور نامعتبر. از 'vocab' برای منوی گرافیکی استفاده کنید." ;;
    esac
else
    main_menu
fi
