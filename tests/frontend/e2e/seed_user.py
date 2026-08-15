#!/usr/bin/env python3
"""Create or delete a throwaway user for the config-page E2E test.

Usage:
    seed_user.py create          # prints {"user_id": ..., "token": ...}
    seed_user.py delete <uid>    # removes the profile (cascades to identity/sessions)

The test user is created directly in PostgreSQL using the app's own connection
settings (`.env` is loaded by app.db.connection), so it never touches real
user data and is fully removed on cleanup.
"""

from __future__ import annotations

import argparse
import json
import secrets
from datetime import datetime, timedelta

from psycopg import connect

from app.db.connection import db_settings


def _connect():
    params = db_settings()
    return connect(
        host=params["host"],
        port=int(params["port"]),
        dbname=params["dbname"],
        user=params["user"],
        password=params["password"],
    )


def create() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO profiles (user_name, partner_name, affection, theme,
                                  session_history, providers_config, model_parameters)
            VALUES ('E2E Tester', 'E2E Partner', 50, 'default', '{}', '{}', '{}')
            RETURNING id
            """
        )
        user_id = cur.fetchone()[0]
        provider_sub = secrets.token_hex(8)
        cur.execute(
            "INSERT INTO user_identities (user_id, provider, provider_sub, email) "
            "VALUES (%s, 'e2e', %s, 'e2e@test.local')",
            (user_id, provider_sub),
        )
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        cur.execute(
            "INSERT INTO user_sessions (token, user_id, created_at, expires_at) "
            "VALUES (%s, %s, %s, %s)",
            (token, user_id, now, now + timedelta(days=7)),
        )
        conn.commit()
    print(json.dumps({"user_id": str(user_id), "token": token}))


def delete(user_id: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM profiles WHERE id = %s", (user_id,))
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    _ = subparsers.add_parser("create")
    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("user_id")
    args = parser.parse_args()
    if args.action == "create":
        create()
    else:
        delete(args.user_id)


if __name__ == "__main__":
    main()
