# FILE: app/profile_analysis.py
# DESCRIPTION: Backward-compatible shim for memory and profile analysis logic.
#              Logic migrated to app/memory/ in Phase 3.

from __future__ import annotations
from app.memory.summarization import (
    detect_important_content,
    should_summarize_memory,
    summarize_memory,
)
from app.memory.profile import (
    normalize_memory_item,
    merge_and_clean_memory,
    summarize_global_player_profile,
    parse_global_profile_summary,
)

# Re-exports for backward compatibility
__all__ = [
    "detect_important_content",
    "should_summarize_memory",
    "summarize_memory",
    "normalize_memory_item",
    "merge_and_clean_memory",
    "summarize_global_player_profile",
    "parse_global_profile_summary",
]
