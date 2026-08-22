from __future__ import annotations

import asyncio
import json

from app.db.connection import AsyncPgSession
from app.tools.registry import execute_tool_event
from app.tools.schemas import make_tool_call_event


async def main() -> None:
    async with AsyncPgSession() as db:
        instance = await db.fetchone(
            "SELECT owner_id, runtime_name, generation FROM sandbox_instances "
            "WHERE state = %s ORDER BY updated_at DESC LIMIT 1",
            ("ready",),
        )
    if not instance:
        raise RuntimeError("No ready sandbox")

    commands = [
        'echo "test"',
        "pwd",
        "ls -la",
        "sh -c 'echo err >&2; exit 7'",
        "whoami",
        "uname -a",
        "cat /etc/os-release",
    ]
    for command in commands:
        event = make_tool_call_event(
            name="terminal",
            arguments={"command": command},
            turn_id="production-probe",
        )
        result = await execute_tool_event(
            event,
            user_id=str(instance["owner_id"]),
        )
        print(
            json.dumps(
                {
                    "command": command,
                    "ok": result.ok,
                    "data": result.data,
                    "error": result.error,
                    "runtime_name_present": bool(instance["runtime_name"]),
                    "generation": instance["generation"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
