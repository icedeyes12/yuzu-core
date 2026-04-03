# FILE: app/memory/models.py
# DESCRIPTION: DEPRECATED - ORM model re-exports.
#              SemanticMemory, EpisodicMemory, ConversationSegment are deprecated.
#              Use app.memory.db_memory instead for all memory operations.
#
# Migration:
#   - SemanticMemory → db_memory.search_similar(fact_type='static')
#   - EpisodicMemory → db_memory.search_similar(fact_type='dynamic', metadata_filter={'source_table': 'episodic_memories'})
#   - ConversationSegment → db_memory.search_similar(fact_type='dynamic', metadata_filter={'source_table': 'conversation_segments'})

from __future__ import annotations

import warnings

warnings.warn(
    "app.memory.models is deprecated. Use app.memory.db_memory instead.",
    DeprecationWarning,
    stacklevel=2
)

# Stub exports for backward compat (None to prevent actual usage)
SemanticMemory = None
EpisodicMemory = None
ConversationSegment = None

__all__ = ["SemanticMemory", "EpisodicMemory", "ConversationSegment"]