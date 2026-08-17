#!/bin/bash

# Exit on error
set -e

echo "=== Yuzu Core Starter ==="

# 1. Check/Start PostgreSQL (Support PRoot Debian & Native Termux)
PGPORT="${PGPORT:-5432}"
PGHOST="${PGHOST:-127.0.0.1}"

if pg_isready -h "$PGHOST" -p "$PGPORT" >/dev/null 2>&1; then
    echo "[DB] PostgreSQL is already running on $PGHOST:$PGPORT."
else
    echo "[DB] PostgreSQL is not running. Starting..."
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
        if pg_isready -h "$PGHOST" -p "$PGPORT" >/dev/null 2>&1; then
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

# 2. Activate virtualenv if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "[Venv] Activated .venv."
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "[Venv] Activated venv."
fi

# 3. Start Yuzu Backend
echo "[App] Starting Yuzu Core API server..."
cd "$SCRIPT_DIR"
exec python main.py
