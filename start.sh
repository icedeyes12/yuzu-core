#!/bin/bash

# Exit on error
set -e

echo "=== Yuzu Companion Starter ==="

# 1. Clean stale locks if any
rm -f /var/lib/postgresql/18/main/postmaster.pid /tmp/.s.PGSQL* /var/run/postgresql/.s.PGSQL* 2>/dev/null || true

# 2. Check/Start PostgreSQL (Support PRoot Debian & Native Termux)
if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "[DB] PostgreSQL is already running."
else
    echo "[DB] PostgreSQL is not running. Starting..."
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
    '-c', 'fsync=off',
    '-c', 'jit=off'
], user=uid, group=gid)
"
    else
        if [ -z "$PGDATA" ]; then
            export PGDATA="$PREFIX/var/lib/postgresql"
        fi
        pg_ctl -D "$PGDATA" start || { echo "[ERROR] Failed to start PostgreSQL. Is initdb run?"; exit 1; }
    fi
    
    for i in $(seq 1 20); do
        if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            echo "[DB] PostgreSQL is ready!"
            break
        fi
        sleep 1
    done
fi

# 3. Check/Start Cloudflared Tunnel
if pgrep -f "cloudflared" >/dev/null 2>&1; then
    echo "[Tunnel] Cloudflared tunnel is already running."
else
    echo "[Tunnel] Starting cloudflared tunnel in background..."
    if [ -f "/root/.cloudflared/config.yml" ]; then
        nohup /usr/local/bin/cloudflared tunnel --config /root/.cloudflared/config.yml run > /var/log/cloudflared.log 2>&1 &
    else
        nohup cloudflared tunnel run yuzu-companion > /dev/null 2>&1 &
    fi
    sleep 3
    if pgrep -f "cloudflared" >/dev/null 2>&1; then
        echo "[Tunnel] Cloudflared tunnel started successfully."
    else
        echo "[WARNING] Cloudflared tunnel failed to start."
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
