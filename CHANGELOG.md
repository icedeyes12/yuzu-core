# Changelog

All notable changes to this project will be documented in this file.

## [1.0.69.29] - 2026-03-27

### Fixed — Memory System (Critical)

- **C1**: `process_messages_for_memory` name collision — canonical function is now `extractor.process_messages_for_memory`; removed shadowing alias from `segmenter.py`
- **C2**: `source_episodic_ids` never populated — `create_episodic_memory` now accepts `source_message_ids` and cross-links episodic↔semantic records
- **C3**: Inconsistent `access_count` initialization — standardized `access_count=1` for new records across all creation paths

### Fixed — Memory System (High)

- **H1**: Idempotency check missed `ConversationSegment` — added `seg_count > 0` to `already_initialized` guard in `app.py` session init
- **H2**: Semantic extraction not idempotent — `upsert_semantic_memory` now uses embedding cosine similarity (>0.95) duplicate detection, matching `memory_store` tool strategy; prevents near-duplicate fact accumulation
- **H3**: Last segment silently discarded when < 5 messages — removed minimum threshold; final group always flushed as a segment
- **H4**: `migrate_history.py` type mismatch — `segment_count = segment_session()` returned `dict`, not `int`; fixed to `seg_result.get('segments_created', 0)`

### Fixed — Memory System (Medium)

- **M1**: Inconsistent `confidence`/`importance` across creation paths — standardized to `confidence=0.7, importance=0.7` in `upsert_semantic_memory` and all migration paths
- **M3**: `models.py` was empty and misleading — now properly re-exports `SemanticMemory`, `EpisodicMemory`, `ConversationSegment` from `app.database` with `__all__`
- **M4**: `source_episode_id` misattributed — all facts in a batch were tagged with `batch[0]["id"]`; fixed to round-robin per-episode attribution
- **M5**: Inconsistent dedup strategy between `memory_store` tool and `upsert_semantic_memory` — resolved (both now use cosine similarity >0.95)

### Added — Memory System

- `app.memory.extractor`: `__all__` exported for clean import surface
- `app.memory.segmenter`: `__all__` exported (`segment_session`, `_detect_boundaries`, `_create_segment`)

## [1.0.69.28v4] - 2026-03-24

### Added
- Embedding model for semantic memory search
- Preview button for HTML codeblocks
- Docker installation support (Dockerfile, docker-compose.yml)

### Fixed
- Various bug fixes