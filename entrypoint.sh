#!/bin/bash
set -e

echo "==> Waiting for PostgreSQL ($POSTGRES_HOST:$POSTGRES_PORT)..."
python << 'EOF'
import socket
import time
import os

host = os.environ.get('POSTGRES_HOST', 'db')
port = int(os.environ.get('POSTGRES_PORT', '5432'))
print(f"Waiting for {host}:{port}...")
start_time = time.time()
connected = False

while time.time() - start_time < 60:
    try:
        with socket.create_connection((host, port), timeout=2):
            connected = True
            print(f"PostgreSQL connection established successfully!")
            break
    except OSError:
        time.sleep(1)

if not connected:
    raise SystemExit("Timed out waiting for PostgreSQL!")
EOF

echo "==> Running Django database migrations..."
python manage.py migrate --noinput

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

# Auto-import old data if present and not yet imported into Postgres
if [ -f "/app/data_dump.json" ] && [ ! -f "/app/media/.data_imported" ]; then
    echo "==> Importing initial SQLite data dump into PostgreSQL..."
    if python manage.py loaddata /app/data_dump.json; then
        echo "==> Data imported successfully!"
        touch /app/media/.data_imported
    else
        echo "==> Notice: Initial loaddata encountered issues or was partially loaded."
        touch /app/media/.data_imported
    fi
fi

echo "==> Starting Uvicorn ASGI Application (Django + FastMCP)..."
exec uvicorn restaurant_system.asgi:application \
    --host 0.0.0.0 \
    --port 8000 \
    --lifespan on \
    --forwarded-allow-ips "*"
