#!/bin/bash
# ==============================================================================
# Nightly Vocab — Automated Database Backup Script
# Keeps the last 14 daily backups and purges older archives.
# Recommended cron entry (runs every night at 03:00 AM):
# 0 3 * * * /home/ubuntu/lexicontext/deploy/backup.sh >> /home/ubuntu/lexicontext/backups/backup.log 2>&1
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${PROJECT_DIR}/backups"

mkdir -p "${BACKUP_DIR}"

# Source environment variables if .env exists
if [ -f "${PROJECT_DIR}/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "${PROJECT_DIR}/.env"
    set +a
fi

DB_USER="${POSTGRES_USER:-lexi}"
DB_NAME="${POSTGRES_DB:-lexicontext}"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
BACKUP_FILENAME="lexicontext_backup_${TIMESTAMP}.sql.gz"
BACKUP_FILEPATH="${BACKUP_DIR}/${BACKUP_FILENAME}"

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting database backup for '${DB_NAME}'..."

# Dump database via docker compose exec
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "${PROJECT_DIR}/docker-compose.yml" exec -T db \
        pg_dump -U "${DB_USER}" -d "${DB_NAME}" | gzip > "${BACKUP_FILEPATH}"
else
    # Fallback to local pg_dump if docker compose is not used directly
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" | gzip > "${BACKUP_FILEPATH}"
fi

# Verify backup was created and is non-empty
if [ ! -s "${BACKUP_FILEPATH}" ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Backup file is missing or empty: ${BACKUP_FILEPATH}" >&2
    rm -f "${BACKUP_FILEPATH}"
    exit 1
fi

FILESIZE="$(du -h "${BACKUP_FILEPATH}" | cut -f1)"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Backup completed successfully: ${BACKUP_FILENAME} (${FILESIZE})"

# Retention policy: Keep the last 14 backups, delete older ones
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Enforcing retention policy (keeping last 14 backups)..."
cd "${BACKUP_DIR}"
ls -1t lexicontext_backup_*.sql.gz 2>/dev/null | tail -n +15 | while read -r old_file; do
    echo "Removing old backup: ${old_file}"
    rm -f "${old_file}"
done

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Backup rotation finished. Total backups retained: $(ls -1 lexicontext_backup_*.sql.gz 2>/dev/null | wc -l)"
