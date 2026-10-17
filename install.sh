#!/usr/bin/env bash
# ==============================================================================
# Nightly Vocab — One-Click Automated Installer (install.sh)
# Inspired by Sanaei x-ui automated deployment scripts
#
# Usage:
#   bash <(curl -Ls https://raw.githubusercontent.com/<user>/<repo>/main/install.sh)
#   or:
#   sudo bash install.sh
# ==============================================================================

set -e

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="/opt/nightly-vocab"
SERVICE_NAME="nightly-vocab"
REPO_URL="https://github.com/bruh-404/nightly-vocab.git"

# 1. Check Root Privileges
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[!] این اسکریپت باید با دسترسی دسترسی مدیر ارشد (root) اجرا شود.${NC}"
    echo -e "لطفاً با دستور ${YELLOW}sudo bash install.sh${NC} مجدداً اجرا نمایید."
    exit 1
fi

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
echo -e "${PURPLE}================================================================${NC}"
echo -e "${GREEN}${BOLD}      اسکریپت نصب و راه‌اندازی خودکار سرور Nightly Vocab         ${NC}"
echo -e "${YELLOW}  یادگیری پیوسته واژگان در بستر متن با سیستم تکرار فاصله‌دار (SRS) ${NC}"
echo -e "${PURPLE}================================================================${NC}"
echo ""

# 2. Detect Operating System & Package Manager
echo -e "${CYAN}[*] تشخیص سیستم‌عامل...${NC}"
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS=$ID
else
    echo -e "${RED}[!] سیستم‌عامل شناسایی نشد.${NC}"
    exit 1
fi

echo -e "${GREEN}[✓] سیستم‌عامل: ${NAME} ${VERSION_ID}${NC}\n"

# 3. Interactive Configuration Prompts
echo -e "${BOLD}${YELLOW}--- مرحله ۱: تنظیم دامنه و گواهی امنیتی SSL ---${NC}"
read -rp "دامنه یا زیردامنه اختصاصی سامانه را وارد کنید (مثال: vocab.domain.com): " USER_DOMAIN
USER_DOMAIN=$(echo "${USER_DOMAIN}" | tr -d ' ' | tr '[:upper:]' '[:lower:]')

while [[ -z "${USER_DOMAIN}" ]]; do
    echo -e "${RED}[!] وارد کردن دامنه برای ساخت گواهی SSL الزامی است.${NC}"
    read -rp "دامنه اختصاصی خود را وارد کنید: " USER_DOMAIN
    USER_DOMAIN=$(echo "${USER_DOMAIN}" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
done

read -rp "ایمیل برای صدور گواهی SSL (اینتر = admin@${USER_DOMAIN}): " USER_EMAIL
if [[ -z "${USER_EMAIL}" ]]; then
    USER_EMAIL="admin@${USER_DOMAIN}"
fi

echo ""
echo -e "${BOLD}${YELLOW}--- مرحله ۲: حساب کاربری مدیر ارشد (Superuser) ---${NC}"
read -rp "نام کاربری یا ایمیل مدیر (پیش‌فرض: admin): " ADMIN_USERNAME
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}

read -rp "رمز عبور مدیر ارشد (اینتر = تولید رمز تصادفی قدرتمند): " ADMIN_PASSWORD
if [[ -z "${ADMIN_PASSWORD}" ]]; then
    ADMIN_PASSWORD=$(tr -dc A-Za-z0-9#_!% 2>/dev/null < /dev/urandom | head -c 16 || echo "AdminVocab2026!#")
    AUTO_GEN_PASS=true
fi

echo ""
echo -e "${BOLD}${YELLOW}--- مرحله ۳: هوش مصنوعی و ربات تلگرام (اختیاری) ---${NC}"
echo -e "${YELLOW}می‌توانید این گزینه‌ها را خالی بگذارید و بعداً در پنل ادمین تنظیم کنید.${NC}"

read -rp "کلید Google Gemini API Key (اینتر برای رد کردن): " GEMINI_API_KEY
read -rp "توکن ربات تلگرام Telegram Bot Token (اینتر برای رد کردن): " TG_BOT_TOKEN
read -rp "آیدی ربات تلگرام با @ مثلا @MyVocabBot (اینتر برای رد کردن): " TG_BOT_USER

if [[ -n "${TG_BOT_USER}" && "${TG_BOT_USER}" != @* ]]; then
    TG_BOT_USER="@${TG_BOT_USER}"
fi

echo ""
echo -e "${BOLD}${YELLOW}--- مرحله ۴: احراز هویت گوگل و سرچ کنسول (اختیاری) ---${NC}"
read -rp "شناسه Google OAuth Client ID (اینتر برای رد کردن): " GOOGLE_CLIENT_ID
read -rp "کلید رمز Google OAuth Client Secret (اینتر برای رد کردن): " GOOGLE_CLIENT_SECRET
read -rp "کد تایید Google Search Console (اینتر برای رد کردن): " GOOGLE_SITE_VERIFICATION

echo ""
echo -e "${CYAN}${BOLD}[*] در حال آماده‌سازی و نصب پیش‌نیازها بر روی سرور...${NC}"

# 4. Install Dependencies without conflicting with other packages
if [[ "${OS}" == "ubuntu" || "${OS}" == "debian" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl git python3 python3-venv python3-pip nginx certbot python3-certbot-nginx
elif [[ "${OS}" == "centos" || "${OS}" == "rhel" || "${OS}" == "almalinux" || "${OS}" == "rocky" ]]; then
    yum install -y -q epel-release || true
    yum install -y -q curl git python3 python3-pip nginx certbot python3-certbot-nginx
fi

# 5. Clone or Copy Codebase to INSTALL_DIR
echo -e "${CYAN}[*] در حال آماده‌سازی فایل‌های سامانه در ${INSTALL_DIR}...${NC}"

# If running directly from cloned directory, sync files
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [[ -f "${SCRIPT_DIR}/manage.py" ]]; then
    mkdir -p "${INSTALL_DIR}"
    cp -r "${SCRIPT_DIR}"/* "${INSTALL_DIR}/"
    cp -r "${SCRIPT_DIR}"/.[!.]* "${INSTALL_DIR}/" 2>/dev/null || true
else
    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        cd "${INSTALL_DIR}"
        git pull origin main || true
    else
        mkdir -p "${INSTALL_DIR}"
        git clone "${REPO_URL}" "${INSTALL_DIR}"
    fi
fi

cd "${INSTALL_DIR}"

# 6. Python Virtual Environment Setup
echo -e "${CYAN}[*] راه‌اندازی Virtualenv اختصاصی پایتون...${NC}"
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip -q
"${INSTALL_DIR}/venv/bin/pip" install -q -r requirements.txt

# 7. Generate Random Cryptographic Keys
echo -e "${CYAN}[*] تولید کلیدهای رمزنگاری قدرتمند...${NC}"
RANDOM_SECRET=$("${INSTALL_DIR}/venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(50))")
RANDOM_FIELD_KEY=$("${INSTALL_DIR}/venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
RANDOM_WEBHOOK_SECRET=$("${INSTALL_DIR}/venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))")

# 8. Create Production .env
echo -e "${CYAN}[*] ایجاد فایل تنظیمات محیطی (.env)...${NC}"
cat > "${INSTALL_DIR}/.env" << EOF
DOMAIN=${USER_DOMAIN}
SITE_URL=https://${USER_DOMAIN}
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=${RANDOM_SECRET}
DEBUG=False
ALLOWED_HOSTS=${USER_DOMAIN},127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://${USER_DOMAIN}
SECURE_SSL_REDIRECT=True

# Database (Default zero-config SQLite, customizable to PostgreSQL)
DATABASE_URL=sqlite:///${INSTALL_DIR}/db.sqlite3

# Encryption & Security
FIELD_ENCRYPTION_KEY=${RANDOM_FIELD_KEY}

# Google OAuth & Search Console
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_SITE_VERIFICATION=${GOOGLE_SITE_VERIFICATION}
ALLOWED_EMAILS=

# Gemini AI Quota
AI_PROVIDER=gemini
GEMINI_API_KEY=${GEMINI_API_KEY}
AI_MODEL=gemini-2.5-flash
AI_DAILY_CALL_LIMIT_PER_USER=30

# Telegram Bot
TELEGRAM_BOT_TOKEN=${TG_BOT_TOKEN}
TELEGRAM_BOT_USERNAME=${TG_BOT_USER}
TELEGRAM_WEBHOOK_SECRET=${RANDOM_WEBHOOK_SECRET}

DJANGO_LOG_LEVEL=INFO
APP_LOG_LEVEL=INFO
EOF
chmod 600 "${INSTALL_DIR}/.env"

# 9. Database Migrations & Static Files
echo -e "${CYAN}[*] اعمال جداول دیتابیس و گرداوری فایل‌های استاتیک...${NC}"
"${INSTALL_DIR}/venv/bin/python" manage.py migrate --noinput --settings=config.settings.prod
"${INSTALL_DIR}/venv/bin/python" manage.py collectstatic --noinput --settings=config.settings.prod

# Create Superuser
echo -e "${CYAN}[*] پیکربندی حساب مدیر ارشد...${NC}"
"${INSTALL_DIR}/venv/bin/python" - << PYEOF
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
username = "${ADMIN_USERNAME}"
password = "${ADMIN_PASSWORD}"
email = "${ADMIN_USERNAME}@${USER_DOMAIN}" if "@" not in username else username

u = User.objects.filter(username=username).first() or User.objects.filter(email=email).first()
if not u:
    User.objects.create_superuser(username=username, email=email, password=password)
else:
    u.set_password(password)
    u.is_superuser = True
    u.is_staff = True
    u.save()

# Seed SiteConfig if values provided
from apps.services.models import SiteConfig
cfg = SiteConfig.get()
if "${GEMINI_API_KEY}":
    cfg.set_shared_ai_key("${GEMINI_API_KEY}")
if "${TG_BOT_TOKEN}":
    cfg.set_tg_bot_token("${TG_BOT_TOKEN}")
if "${TG_BOT_USER}":
    cfg.tg_bot_username = "${TG_BOT_USER}"
if "${GOOGLE_CLIENT_ID}":
    cfg.google_client_id = "${GOOGLE_CLIENT_ID}"
if "${GOOGLE_CLIENT_SECRET}":
    cfg.set_google_client_secret("${GOOGLE_CLIENT_SECRET}")
if "${GOOGLE_SITE_VERIFICATION}":
    cfg.google_site_verification = "${GOOGLE_SITE_VERIFICATION}"
cfg.save()
cfg.sync_google_social_app()
PYEOF

# 10. Configure Systemd Service
echo -e "${CYAN}[*] ایجاد سرویس سیستمی (${SERVICE_NAME}.service)...${NC}"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Nightly Vocab Web Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

# 11. Obtain SSL Certificate and Configure Nginx
echo -e "${CYAN}[*] درخواست گواهی رایگان SSL از Let's Encrypt برای ${USER_DOMAIN}...${NC}"
systemctl stop nginx 2>/dev/null || true

# Try to acquire SSL
if certbot certonly --standalone -d "${USER_DOMAIN}" --non-interactive --agree-tos --email "${USER_EMAIL}"; then
    SSL_OK=true
else
    echo -e "${YELLOW}[!] هشدار: گواهی اتوماتیک Let's Encrypt صادر نشد (ممکن است رکورد DNS دامنه هنوز در اینترنت منتشر نشده باشد).${NC}"
    echo -e "${YELLOW}سایت روی HTTP موقتاً فعال می‌شود و بعداً با دستور 'vocab ssl' می‌توانید گواهی را ثبت کنید.${NC}"
    SSL_OK=false
fi

# Configure Nginx Virtual Host
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
if [[ "${SSL_OK}" == "true" ]]; then
    cat > "/etc/nginx/sites-available/nightly-vocab" << EOF
server {
    listen 80;
    server_name ${USER_DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${USER_DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${USER_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${USER_DOMAIN}/privkey.pem;

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
else
    cat > "/etc/nginx/sites-available/nightly-vocab" << EOF
server {
    listen 80;
    server_name ${USER_DOMAIN};

    client_max_body_size 25M;

    location /static/ {
        alias ${INSTALL_DIR}/staticfiles/;
        expires 30d;
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
fi

ln -sf "/etc/nginx/sites-available/nightly-vocab" "/etc/nginx/sites-enabled/nightly-vocab"
nginx -t && systemctl restart nginx
systemctl enable nginx

# 12. Install Global Management Command 'vocab'
echo -e "${CYAN}[*] نصب ابزار مدیریت سرور (دستور 'vocab')...${NC}"
cp "${INSTALL_DIR}/scripts/vocab.sh" "/usr/local/bin/vocab"
chmod +x "/usr/local/bin/vocab"

# 13. Final Success Summary
clear
echo -e "${GREEN}${BOLD}"
cat << "EOF"
  ==============================================================
   🎉 تبریک! سامانه Nightly Vocab با موفقیت روی سرور نصب گردید
  ==============================================================
EOF
echo -e "${NC}"
if [[ "${SSL_OK}" == "true" ]]; then
    echo -e "  🌐 آدرس وب‌سایت:      ${CYAN}https://${USER_DOMAIN}${NC}"
    echo -e "  ⚙️ پنل مدیریت ارشد:    ${CYAN}https://${USER_DOMAIN}/manage/${NC}"
else
    echo -e "  🌐 آدرس وب‌سایت (HTTP): ${CYAN}http://${USER_DOMAIN}${NC}"
    echo -e "  ⚙️ پنل مدیریت ارشد:     ${CYAN}http://${USER_DOMAIN}/manage/${NC}"
fi
echo -e "  👤 نام کاربری مدیر:     ${BOLD}${ADMIN_USERNAME}${NC}"
echo -e "  🔑 رمز عبور مدیر:       ${YELLOW}${BOLD}${ADMIN_PASSWORD}${NC}"
echo ""
echo -e "${PURPLE}==============================================================${NC}"
echo -e "${BOLD}${YELLOW}📌 نحوه مدیریت سرور در هر زمان:${NC}"
echo -e "  کافیست در ترمینال سرور دستور زیر را تایپ کنید:"
echo -e "  👉  ${GREEN}${BOLD}vocab${NC}"
echo -e "  با این دستور می‌توانید لاگ‌ها را ببینید، نسخه جدید را آپدیت کنید،"
echo -e "  کلیدهای هوش مصنوعی و ربات تلگرام را عوض کرده یا دیتابیس را بکاپ بگیرید."
echo -e "${PURPLE}==============================================================${NC}"
echo ""
