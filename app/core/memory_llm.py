from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_LLM_DELAY = 3.0
_last_memory_llm_call = 0.0


async def memory_llm_call(
    ai_manager: Any, messages: list[dict], **kwargs
) -> str | None:
    """Call the memory LLM with the shared pipeline rate limit."""
    global _last_memory_llm_call

    total_chars = sum(
        len(message.get("content", ""))
        if isinstance(message.get("content"), str)
        else 0
        for message in messages
    )
    logger.debug("[MEMORY_LLM] Sending %s chars to LLM...", total_chars)

    elapsed = time.time() - _last_memory_llm_call
    if elapsed < _MEMORY_LLM_DELAY:
        await asyncio.sleep(_MEMORY_LLM_DELAY - elapsed)

    try:
        result = await ai_manager._internal_llm_call(
            messages, source="memory_pipeline", **kwargs
        )
        _last_memory_llm_call = time.time()
        if result:
            logger.debug("[MEMORY_LLM] Response received: %s chars", len(result))
        else:
            logger.warning(
                "[MEMORY_LLM] LLM returned None - possible context overflow, "
                "rate limit, or empty response"
            )
        return result
    except TimeoutError as exc:
        logger.warning(
            "[MEMORY_LLM] Timeout after %ss: %s", kwargs.get("timeout", 30), exc
        )
        return None
    except Exception as exc:
        logger.info("[MEMORY_LLM] skipped (%s)", type(exc).__name__)
        return None
