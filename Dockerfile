# Production Dockerfile for Nightly Vocab
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies (curl for healthchecks, postgresql-client for backups and administration)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root application user
RUN groupadd -r lexi && useradd -r -g lexi -d /app -s /bin/bash lexi

# Copy application source code
COPY . /app/

# Create staticfiles directory, set ownership and executable permissions
RUN mkdir -p /app/staticfiles && \
    chown -R lexi:lexi /app && \
    chmod +x /app/deploy/entrypoint.sh && \
    chmod +x /app/deploy/backup.sh 2>/dev/null || true

# Collect static files during image build
RUN DJANGO_SECRET_KEY="build-dummy-secret-key-for-collectstatic" \
    FIELD_ENCRYPTION_KEY="Zyk0_cNjhzLj0tmOXFDB241OWo7EIM-2ns-nJgz3jVg=" \
    DATABASE_URL="sqlite:///:memory:" \
    python manage.py collectstatic --noinput

USER lexi

EXPOSE 8000

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--workers", "3", "--bind", "0.0.0.0:8000"]
