#!/bin/bash

# Exit on error
set -e

echo "=== Yuzu Companion Starter ==="

# 1. Check/Start PostgreSQL (Support PRoot Debian & Native Termux)
if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "[DB] PostgreSQL is already running."
else
    echo "[DB] PostgreSQL is not running. Starting..."
    # Clean stale PID file only after confirming PostgreSQL is stopped
    if [ -f "/var/lib/postgresql/18/main/postmaster.pid" ]; then
        rm -f /var/lib/postgresql/18/main/postmaster.pid
    fi
    if [ -f "/usr/lib/postgresql/18/bin/postgres" ]; then
        python3 -c "
import subprocess, pwd
uid = pwd.getpwnam('postgres').pw_uid
gid = pwd.getpwnam('postgres').pw_gid
subprocess.Popen([
    '/usr/lib/postgresql/18/bin/postgres',
    '-D', '/var/lib/postgresql/18/main',
    '-c', 'config_file=/etc/postgresql/18/main/postgresql.conf',
    '-c', 'shared_memory_type=mmap',
    '-c', 'dynamic_shared_memory_type=mmap',
    '-c', 'jit=off'
], user=uid, group=gid)
"
    else
        if [ -z "$PGDATA" ]; then
            export PGDATA="$PREFIX/var/lib/postgresql"
        fi
        pg_ctl -D "$PGDATA" start || { echo "[ERROR] Failed to start PostgreSQL. Is initdb run?"; exit 1; }
    fi
    
    pg_ready=0
    for i in $(seq 1 20); do
        if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            echo "[DB] PostgreSQL is ready!"
            pg_ready=1
            break
        fi
        sleep 1
    done
    if [ "$pg_ready" -eq 0 ]; then
        echo "[ERROR] PostgreSQL failed to become ready after 20 attempts."
        exit 1
    fi
fi

# 3. Check/Start Cloudflared Tunnel
if pgrep -f "cloudflared tunnel.*yuzu-companion" >/dev/null 2>&1; then
    echo "[Tunnel] Cloudflared tunnel is already running."
else
    echo "[Tunnel] Starting cloudflared tunnel in background..."
    cloudflared_bin=$(command -v cloudflared)
    if [ -z "$cloudflared_bin" ]; then
        echo "[WARNING] cloudflared executable not found in PATH."
    elif [ -f "/root/.cloudflared/config.yml" ]; then
        nohup "$cloudflared_bin" tunnel --config /root/.cloudflared/config.yml run > /var/log/cloudflared.log 2>&1 &
        sleep 3
        if pgrep -f "cloudflared tunnel.*yuzu-companion" >/dev/null 2>&1; then
            echo "[Tunnel] Cloudflared tunnel started successfully."
        else
            echo "[WARNING] Cloudflared tunnel failed to start."
        fi
    else
        nohup "$cloudflared_bin" tunnel run yuzu-companion > /dev/null 2>&1 &
        sleep 3
        if pgrep -f "cloudflared tunnel.*yuzu-companion" >/dev/null 2>&1; then
            echo "[Tunnel] Cloudflared tunnel started successfully."
        else
            echo "[WARNING] Cloudflared tunnel failed to start."
        fi
    fi
fi

# 4. Activate venv if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "[Venv] Activated .venv."
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "[Venv] Activated venv."
fi

# 5. Start Yuzu Backend
echo "[App] Starting Yuzu Companion server..."
cd "$SCRIPT_DIR"
exec python main.py
