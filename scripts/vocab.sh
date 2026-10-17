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
        echo -e "${RED}[!] This script must be run with root privileges.${NC}"
        echo -e "Please run with: ${YELLOW}sudo vocab${NC}"
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
    echo -e "${YELLOW}  Nightly Vocab / LexiContext — Server Management CLI${NC}"
    echo -e "${PURPLE}  ======================================================${NC}"
    echo ""
}

# Check Service Status
check_status() {
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo -e "  Service Status: ${GREEN}● Active (Running)${NC}"
    else
        echo -e "  Service Status: ${RED}○ Inactive (Stopped)${NC}"
    fi

    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        echo -e "  Auto-Start:     ${GREEN}Enabled${NC}"
    else
        echo -e "  Auto-Start:     ${YELLOW}Disabled${NC}"
    fi

    if [[ -f "${ENV_FILE}" ]]; then
        local domain=$(grep -E "^DOMAIN=" "${ENV_FILE}" | cut -d '=' -f2- | tr -d ' "' || echo "Not configured")
        echo -e "  System URL:     ${CYAN}https://${domain}${NC}"
    fi
    echo ""
}

# Start Service
start_service() {
    echo -e "${YELLOW}[*] Starting service...${NC}"
    systemctl start "${SERVICE_NAME}"
    sleep 2
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo -e "${GREEN}[✓] Service started successfully.${NC}"
    else
        echo -e "${RED}[!] Failed to start service. Check logs:${NC}"
        journalctl -u "${SERVICE_NAME}" -n 20 --no-pager
    fi
}

# Stop Service
stop_service() {
    echo -e "${YELLOW}[*] Stopping service...${NC}"
    systemctl stop "${SERVICE_NAME}"
    echo -e "${GREEN}[✓] Service stopped.${NC}"
}

# Restart Service
restart_service() {
    echo -e "${YELLOW}[*] Restarting service...${NC}"
    systemctl restart "${SERVICE_NAME}"
    sleep 2
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo -e "${GREEN}[✓] Service restarted successfully.${NC}"
    else
        echo -e "${RED}[!] Failed to restart service.${NC}"
        journalctl -u "${SERVICE_NAME}" -n 20 --no-pager
    fi
}

# View Live Logs
view_logs() {
    echo -e "${CYAN}[*] Streaming live logs (Press Ctrl+C to exit)...${NC}"
    sleep 1
    journalctl -u "${SERVICE_NAME}" -f -n 50
}

# Update from GitHub
update_app() {
    echo -e "${CYAN}${BOLD}[*] Checking and pulling latest release from GitHub...${NC}"
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
        echo -e "${RED}[!] Directory is not a git repository (${INSTALL_DIR}).${NC}"
        return 1
    fi

    cd "${INSTALL_DIR}"
    
    # Save local edits if any
    git stash >/dev/null 2>&1 || true
    
    # Pull latest commits
    echo -e "${YELLOW}[1/4] Pulling latest updates (git pull)...${NC}"
    git pull origin main || git pull origin master

    # Update dependencies
    echo -e "${YELLOW}[2/4] Updating Python dependencies...${NC}"
    ${PIP_BIN} install -q -r requirements.txt

    # Run migrations
    echo -e "${YELLOW}[3/4] Applying database migrations...${NC}"
    ${PYTHON_BIN} manage.py migrate --noinput --settings=config.settings.prod

    # Collect static files
    echo -e "${YELLOW}[4/4] Updating static assets...${NC}"
    ${PYTHON_BIN} manage.py collectstatic --noinput --settings=config.settings.prod

    # Restart service
    echo -e "${YELLOW}[*] Restarting service...${NC}"
    systemctl restart "${SERVICE_NAME}"
    
    echo -e "${GREEN}${BOLD}[✓] Update completed successfully! Running the latest version.${NC}"
}

# Change Domain & SSL
configure_ssl() {
    echo -e "${CYAN}${BOLD}[*] Configure Domain & SSL Certificate (Let's Encrypt)...${NC}"
    read -rp "Enter new domain name (e.g. vocab.yourdomain.com): " NEW_DOMAIN
    NEW_DOMAIN=$(echo "${NEW_DOMAIN}" | tr -d ' ' | tr '[:upper:]' '[:lower:]')

    if [[ -z "${NEW_DOMAIN}" ]]; then
        echo -e "${RED}[!] Domain cannot be empty.${NC}"
        return 1
    fi

    read -rp "Enter email for SSL certificate (Enter = admin@${NEW_DOMAIN}): " SSL_EMAIL
    if [[ -z "${SSL_EMAIL}" ]]; then
        SSL_EMAIL="admin@${NEW_DOMAIN}"
    fi

    echo -e "${YELLOW}[*] Obtaining SSL certificate for ${NEW_DOMAIN}...${NC}"
    systemctl stop nginx || true
    certbot certonly --standalone -d "${NEW_DOMAIN}" --non-interactive --agree-tos --email "${SSL_EMAIL}" || {
        echo -e "${RED}[!] Failed to obtain SSL certificate. Verify DNS A record points to this server and port 80 is open.${NC}"
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
    echo -e "${GREEN}[✓] Domain and SSL updated successfully: https://${NEW_DOMAIN}${NC}"
}

# Change AI and Bot Secrets
configure_secrets() {
    echo -e "${CYAN}${BOLD}[*] Configure API Keys & System Secrets${NC}"
    echo -e "${YELLOW}(Press Enter to leave any value unchanged)${NC}\n"

    read -rp "Google Gemini API Key: " NEW_AI_KEY
    if [[ -n "${NEW_AI_KEY}" ]]; then
        sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${NEW_AI_KEY}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] Gemini API Key saved.${NC}"
    fi

    read -rp "Telegram Bot Token: " NEW_TG_TOKEN
    if [[ -n "${NEW_TG_TOKEN}" ]]; then
        sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${NEW_TG_TOKEN}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] Telegram Bot Token saved.${NC}"
    fi

    read -rp "Telegram Bot Username (e.g. @NightlyVocabBot): " NEW_TG_USER
    if [[ -n "${NEW_TG_USER}" ]]; then
        [[ "${NEW_TG_USER}" != @* ]] && NEW_TG_USER="@${NEW_TG_USER}"
        sed -i "s|^TELEGRAM_BOT_USERNAME=.*|TELEGRAM_BOT_USERNAME=${NEW_TG_USER}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] Telegram Bot Username saved.${NC}"
    fi

    read -rp "Google OAuth Client ID: " NEW_G_ID
    if [[ -n "${NEW_G_ID}" ]]; then
        sed -i "s|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${NEW_G_ID}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] Google Client ID saved.${NC}"
    fi

    read -rp "Google OAuth Client Secret: " NEW_G_SECRET
    if [[ -n "${NEW_G_SECRET}" ]]; then
        sed -i "s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${NEW_G_SECRET}|" "${ENV_FILE}"
        echo -e "${GREEN}[✓] Google Client Secret saved.${NC}"
    fi

    read -rp "Google Search Console Verification Code: " NEW_G_VERIFY
    if [[ -n "${NEW_G_VERIFY}" ]]; then
        if grep -q "^GOOGLE_SITE_VERIFICATION=" "${ENV_FILE}"; then
            sed -i "s|^GOOGLE_SITE_VERIFICATION=.*|GOOGLE_SITE_VERIFICATION=${NEW_G_VERIFY}|" "${ENV_FILE}"
        else
            echo "GOOGLE_SITE_VERIFICATION=${NEW_G_VERIFY}" >> "${ENV_FILE}"
        fi
        echo -e "${GREEN}[✓] Google Search Console verification code saved.${NC}"
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
    echo -e "\n${GREEN}[✓] All secrets saved, synced with database, and service restarted.${NC}"
}

# Create Superuser / Change Admin Password
manage_admin() {
    echo -e "${CYAN}${BOLD}[*] Superuser Administration${NC}"
    echo "1) Create a new superuser account"
    echo "2) Change password of an existing user"
    read -rp "Select option [1-2]: " ADMIN_OPT

    cd "${INSTALL_DIR}"
    if [[ "${ADMIN_OPT}" == "1" ]]; then
        ${PYTHON_BIN} manage.py createsuperuser --settings=config.settings.prod
    elif [[ "${ADMIN_OPT}" == "2" ]]; then
        read -rp "Enter username or email: " ADMIN_UNAME
        ${PYTHON_BIN} manage.py changepassword "${ADMIN_UNAME}" --settings=config.settings.prod
    fi
}

# Backup Database & Media
backup_data() {
    local BACKUP_DIR="/var/backups/nightly-vocab"
    mkdir -p "${BACKUP_DIR}"
    local TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    local BACKUP_FILE="${BACKUP_DIR}/vocab_backup_${TIMESTAMP}.tar.gz"

    echo -e "${YELLOW}[*] Creating full backup archive...${NC}"
    cd "${INSTALL_DIR}"
    tar -czf "${BACKUP_FILE}" \
        --exclude='venv' \
        --exclude='staticfiles' \
        --exclude='__pycache__' \
        .env db.sqlite3 media/ 2>/dev/null || true

    echo -e "${GREEN}[✓] Backup archive successfully created at:${NC}"
    echo -e "    ${CYAN}${BACKUP_FILE}${NC}"
}

# Uninstall
uninstall_app() {
    echo -e "${RED}${BOLD}[!] WARNING: This will terminate and remove the Nightly Vocab system and services.${NC}"
    read -rp "Are you sure you want to proceed? (y/N): " CONFIRM
    if [[ "${CONFIRM}" =~ ^[Yy]$ ]]; then
        systemctl stop "${SERVICE_NAME}" || true
        systemctl disable "${SERVICE_NAME}" || true
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        rm -f "/etc/nginx/sites-enabled/nightly-vocab"
        rm -f "/etc/nginx/sites-available/nightly-vocab"
        rm -f "/usr/local/bin/vocab"
        systemctl daemon-reload
        systemctl restart nginx || true
        echo -e "${YELLOW}Do you also want to permanently delete all project files and database in ${INSTALL_DIR}? (y/N): ${NC}"
        read -rp "" DEL_DATA
        if [[ "${DEL_DATA}" =~ ^[Yy]$ ]]; then
            rm -rf "${INSTALL_DIR}"
            echo -e "${GREEN}[✓] Files permanently deleted.${NC}"
        fi
        echo -e "${GREEN}[✓] Nightly Vocab has been successfully uninstalled.${NC}"
        exit 0
    else
        echo -e "${YELLOW}[*] Uninstallation cancelled.${NC}"
    fi
}

# Interactive CLI Menu
main_menu() {
    check_root
    while true; do
        show_banner
        check_status
        echo -e "${BOLD}Management Menu:${NC}"
        echo -e "  ${GREEN}1)${NC} Start service"
        echo -e "  ${RED}2)${NC} Stop service"
        echo -e "  ${YELLOW}3)${NC} Restart service"
        echo -e "  ${CYAN}4)${NC} View live logs"
        echo -e "  ${PURPLE}5)${NC} Update system from GitHub"
        echo -e "  ${BLUE}6)${NC} Change domain & SSL"
        echo -e "  ${YELLOW}7)${NC} Configure API keys & secrets"
        echo -e "  ${CYAN}8)${NC} Manage admin account"
        echo -e "  ${GREEN}9)${NC} Backup database & media"
        echo -e "  ${RED}10)${NC} Uninstall system"
        echo -e "  ${BOLD}0)${NC} Exit"
        echo ""
        read -rp "Please select an option [0-10]: " CHOICE

        case "${CHOICE}" in
            1) start_service; read -rp "Press Enter to continue..." ;;
            2) stop_service; read -rp "Press Enter to continue..." ;;
            3) restart_service; read -rp "Press Enter to continue..." ;;
            4) view_logs ;;
            5) update_app; read -rp "Press Enter to continue..." ;;
            6) configure_ssl; read -rp "Press Enter to continue..." ;;
            7) configure_secrets; read -rp "Press Enter to continue..." ;;
            8) manage_admin; read -rp "Press Enter to continue..." ;;
            9) backup_data; read -rp "Press Enter to continue..." ;;
            10) uninstall_app ;;
            0) echo -e "${GREEN}Have a great day!${NC}"; exit 0 ;;
            *) echo -e "${RED}[!] Invalid option.${NC}"; sleep 1 ;;
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
        *) echo "Unknown command. Run 'vocab' to open the interactive management menu." ;;
    esac
else
    main_menu
fi
