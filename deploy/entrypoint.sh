#!/bin/sh
set -e

# Wait for PostgreSQL database if DATABASE_URL starts with postgres:// or postgresql://
if echo "$DATABASE_URL" | grep -Eq "^postgres(ql)?://"; then
    echo "Waiting for PostgreSQL database to be available..."
    python - <<'EOF'
import os
import sys
import time
import urllib.parse
import socket

db_url = os.environ.get("DATABASE_URL", "")
parsed = urllib.parse.urlparse(db_url)
host = parsed.hostname or "db"
port = parsed.port or 5432

timeout = 45
start_time = time.time()
while time.time() - start_time < timeout:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"PostgreSQL is accepting connections at {host}:{port}.")
            sys.exit(0)
    except (socket.error, OSError):
        time.sleep(1)

print(f"Timed out waiting for database connection at {host}:{port}.", file=sys.stderr)
sys.exit(1)
EOF
fi

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Execute the container command (gunicorn by default, or custom command e.g. scheduler)
echo "Starting application process: $@"
exec "$@"
