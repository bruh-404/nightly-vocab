"""Tests for production hardening, deployment assets, and security settings (Step 11)."""
import importlib
import os
from pathlib import Path
from unittest.mock import patch

import environ
import pytest
import yaml
from django.test import Client

BASE_DIR = Path(__file__).resolve().parent.parent


def test_healthz_endpoint(client: Client) -> None:
    """Verifies that the /healthz/ healthcheck endpoint returns 200 OK."""
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.content == b"OK"


def test_dockerfile_contents() -> None:
    """Verifies Dockerfile meets all production hardening specifications."""
    dockerfile_path = BASE_DIR / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at project root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in content
    assert "useradd" in content and "lexi" in content, "Must use non-root application user"
    assert "USER lexi" in content
    assert "collectstatic --noinput" in content
    assert "ENTRYPOINT" in content and "entrypoint.sh" in content
    assert "gunicorn" in content


def test_docker_compose_structure() -> None:
    """Verifies docker-compose.yml defines required services and valid syntax."""
    compose_path = BASE_DIR / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist at project root"

    content = compose_path.read_text(encoding="utf-8")
    # Replace variable substitutions for simple YAML parsing test
    content_clean = content.replace("${POSTGRES_PASSWORD:?Database password required}", "dummy_pass")
    content_clean = content_clean.replace("${DOMAIN:?Domain required for Caddy}", "vocab.example.com")
    data = yaml.safe_load(content_clean)

    services = data.get("services", {})
    assert "db" in services
    assert "web" in services
    assert "scheduler" in services
    assert "caddy" in services

    # Verify db healthcheck
    assert "healthcheck" in services["db"]
    # Verify web healthcheck
    assert "healthcheck" in services["web"]
    # Verify scheduler loops send_reminders
    assert "send_reminders" in " ".join(services["scheduler"].get("command", []))
    # Verify caddy ports
    assert "80:80" in services["caddy"]["ports"]
    assert "443:443" in services["caddy"]["ports"]


def test_caddyfile_structure() -> None:
    """Verifies Caddyfile reverse-proxying and compression configuration."""
    caddy_path = BASE_DIR / "Caddyfile"
    assert caddy_path.exists(), "Caddyfile must exist at project root"

    content = caddy_path.read_text(encoding="utf-8")
    assert "{$DOMAIN}" in content
    assert "encode gzip zstd" in content
    assert "reverse_proxy web:8000" in content


def test_entrypoint_script() -> None:
    """Verifies entrypoint.sh script logic."""
    entrypoint_path = BASE_DIR / "deploy" / "entrypoint.sh"
    assert entrypoint_path.exists()

    content = entrypoint_path.read_text(encoding="utf-8")
    assert "migrate --noinput" in content
    assert 'exec "$@"' in content


def test_backup_script() -> None:
    """Verifies deploy/backup.sh retention and dump commands."""
    backup_path = BASE_DIR / "deploy" / "backup.sh"
    assert backup_path.exists()

    content = backup_path.read_text(encoding="utf-8")
    assert "pg_dump" in content
    assert "gzip" in content
    assert "tail -n +15" in content, "Must retain 14 backups and purge older ones"


def test_env_example_completeness() -> None:
    """Verifies that .env.example contains all required environment keys."""
    env_example = BASE_DIR / ".env.example"
    assert env_example.exists()

    content = env_example.read_text(encoding="utf-8")
    required_keys = [
        "DOMAIN",
        "DJANGO_SETTINGS_MODULE",
        "DJANGO_SECRET_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "FIELD_ENCRYPTION_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "AI_PROVIDER",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
    ]
    for key in required_keys:
        assert f"{key}=" in content, f"Missing {key} in .env.example"


def test_readme_runbook_content() -> None:
    """Verifies README.md documents the runbook, backup cron, and restore procedure."""
    readme_path = BASE_DIR / "README.md"
    assert readme_path.exists()

    content = readme_path.read_text(encoding="utf-8")
    assert "Ubuntu 24.04" in content
    assert "createsuperuser" in content
    assert "set_telegram_webhook" in content
    assert "backup.sh" in content
    assert "psql" in content, "Must document disaster recovery restore command"


def test_prod_settings_fail_loudly_without_secrets() -> None:
    """Verifies prod settings raise ImproperlyConfigured when secrets are missing."""
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}, clear=True):
        with pytest.raises(environ.ImproperlyConfigured):
            import config.settings.prod as prod_mod
            importlib.reload(prod_mod)


def test_prod_security_configuration() -> None:
    """Verifies prod settings security flags with valid mock environment."""
    mock_env = {
        "DJANGO_SECRET_KEY": "dummy-production-secret-key-at-least-50-characters-long",
        "FIELD_ENCRYPTION_KEY": "Zyk0_cNjhzLj0tmOXFDB241OWo7EIM-2ns-nJgz3jVg=",
        "DATABASE_URL": "sqlite:///:memory:",
        "ALLOWED_HOSTS": "vocab.example.com,web",
        "CSRF_TRUSTED_ORIGINS": "https://vocab.example.com",
    }
    with patch.dict(os.environ, mock_env, clear=False):
        import config.settings.prod as prod_mod
        importlib.reload(prod_mod)

        assert prod_mod.DEBUG is False
        assert prod_mod.SESSION_COOKIE_SECURE is True
        assert prod_mod.CSRF_COOKIE_SECURE is True
        assert prod_mod.SESSION_COOKIE_HTTPONLY is True
        assert prod_mod.X_FRAME_OPTIONS == "DENY"
        assert prod_mod.SECURE_HSTS_SECONDS == 31536000
        assert "LOGGING" in dir(prod_mod)
        assert "console" in prod_mod.LOGGING["handlers"]
