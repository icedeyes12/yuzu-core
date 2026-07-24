#!/bin/bash

# Exit on error
set -e

echo "=== Yuzu Companion Starter ==="

# 1. Check/Start PostgreSQL
if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "[DB] PostgreSQL is already running."
else
    echo "[DB] PostgreSQL is not running. Starting..."
    # Termux default db path is typically ~/../usr/var/lib/postgresql or configured in PGDATA
    # If PGDATA env is set, pg_ctl will use it. Otherwise we try default init.
    if [ -z "$PGDATA" ]; then
        export PGDATA="$PREFIX/var/lib/postgresql"
    fi
    pg_ctl -D "$PGDATA" start || { echo "[ERROR] Failed to start PostgreSQL. Is initdb run?"; exit 1; }
    sleep 2
fi

# 2. Check/Start Cloudflared Tunnel
if pgrep -f "cloudflared tunnel run yuzu-companion" >/dev/null 2>&1; then
    echo "[Tunnel] Cloudflared tunnel is already running."
else
    echo "[Tunnel] Starting cloudflared tunnel in background..."
    nohup cloudflared tunnel run yuzu-companion > /dev/null 2>&1 &
    sleep 3
    if pgrep -f "cloudflared tunnel run yuzu-companion" >/dev/null 2>&1; then
        echo "[Tunnel] Cloudflared tunnel started successfully."
    else
        echo "[WARNING] Cloudflared tunnel failed to start. Check 'cloudflared tunnel run yuzu-companion' manually."
    fi
fi

# 3. Start Yuzu Backend
echo "[App] Starting Yuzu Companion server..."
exec python main.py
