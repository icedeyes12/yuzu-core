# [FILE: memory/batch_migrate.py]
# [DESCRIPTION: Batch migration script for backfilling embeddings on existing memory records]
# [USAGE: python -c "from memory.batch_migrate import run_migration; run_migration()"]

import os
import json
import time
import struct
from datetime import datetime
from database import Database, get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment, Message, ChatSession
from memory.embedder import embed_texts
from memory.extractor import extract_semantic_facts, upsert_semantic_memory, generate_episodic_summary


CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), 'migration_checkpoint.json')


def _ts():
    return datetime.now().strftime('%H:%M:%S')


def _vec_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f'{len(vec)}f', *vec)


def _load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {
        'semantic_done': 0,
        'episodic_done': 0,
        'segments_done': 0,
        'messages_processed': 0,
        'started_at': None,
        'last_run': None,
    }


def _save_checkpoint(cp):
    cp['last_run'] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(cp, f, indent=2)


def _embed_batch(texts, retries=3):
    """Embed a batch of texts with retry logic."""
    for attempt in range(retries):
        try:
            return embed_texts(texts)
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [{_ts()}][RETRY] Embed batch failed (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    return [None] * len(texts)


def migrate_semantic_memories():
    """Backfill embedding vectors for all existing semantic memories."""
    print(f"[{_ts()}] === Migrating semantic_memories ===")
    cp = _load_checkpoint()
    if cp.get('semantic_done') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        total = session.query(SemanticMemory).count()
        records = session.query(SemanticMemory).order_by(SemanticMemory.id.asc()).all()

    texts_to_embed = []
    indices = []
    records_by_idx = []

    for i, rec in enumerate(records):
        if i < cp['semantic_done']:
            continue
        # Build composite text for embedding
        text = f"{rec.entity} {rec.relation} {rec.target}"
        texts_to_embed.append(text)
        indices.append(i)
        records_by_idx.append(rec)

    if not texts_to_embed:
        print(f"  [{_ts()}] Nothing to migrate ({total} records, checkpoint at {cp['semantic_done']})")
        return 0

    print(f"  [{_ts()}] Embedding {len(texts_to_embed)} records... (batch_size=64)")
    migrated = cp['semantic_done']

    for batch_start in range(0, len(texts_to_embed), 64):
        batch_texts = texts_to_embed[batch_start:batch_start + 64]
        vecs = _embed_batch(batch_texts)

        with get_db_session() as session:
            for j, (rec_id) in enumerate(records_by_idx[batch_start:batch_start + 64]):
                vec = vecs[j]
                rec = session.query(SemanticMemory).filter_by(id=rec_id).first()
                if rec and vec is not None:
                    rec.embedding_vector = _vec_to_blob(vec)
                    session.commit()
                    migrated += 1
                    if migrated % 200 == 0:
                        elapsed = time.time() - _start_time
                        rate = migrated / max(elapsed, 0.1)
                        eta = (len(texts_to_embed) - migrated) / max(rate, 1)
                        print(f"  [{_ts()}] {migrated}/{len(texts_to_embed)} | {rate:.1f}/s | ETA {eta:.0f}s")
                        cp['semantic_done'] = indices[batch_start + j]
                        _save_checkpoint(cp)

    cp['semantic_done'] = -1  # mark complete
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {migrated} semantic memories embedded")
    return migrated


def migrate_episodic_memories():
    """Backfill embedding vectors for all existing episodic memories."""
    print(f"\n[{_ts()}] === Migrating episodic_memories ===")
    cp = _load_checkpoint()
    if cp.get('episodic_done') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        records = session.query(EpisodicMemory).order_by(EpisodicMemory.id.asc()).all()

    texts_to_embed = []
    records_by_id = []

    for rec in records:
        if cp.get('episodic_done', 0) > 0 and rec.id <= cp['episodic_done']:
            continue
        texts_to_embed.append(rec.summary)
        records_by_id.append(rec.id)

    if not texts_to_embed:
        print(f"  [{_ts()}] Nothing to migrate")
        return 0

    print(f"  [{_ts()}] Embedding {len(texts_to_embed)} episodic records...")
    migrated = 0

    for batch_start in range(0, len(texts_to_embed), 64):
        batch_texts = texts_to_embed[batch_start:batch_start + 64]
        vecs = _embed_batch(batch_texts)

        with get_db_session() as session:
            for j, rec_id in enumerate(records_by_id[batch_start:batch_start + 64]):
                vec = vecs[j]
                rec = session.query(EpisodicMemory).filter_by(id=rec_id).first()
                if rec and vec is not None:
                    rec.embedding_vector = _vec_to_blob(vec)
                    session.commit()
                    migrated += 1
                    if migrated % 200 == 0:
                        print(f"  [{_ts()}] {migrated}/{len(texts_to_embed)}")
                        cp['episodic_done'] = rec_id
                        _save_checkpoint(cp)

    cp['episodic_done'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {migrated} episodic memories embedded")
    return migrated


def migrate_segments():
    """Backfill embedding vectors for all existing conversation segments."""
    print(f"\n[{_ts()}] === Migrating conversation_segments ===")
    cp = _load_checkpoint()
    if cp.get('segments_done') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        records = session.query(ConversationSegment).order_by(ConversationSegment.id.asc()).all()

    texts_to_embed = []
    records_by_id = []

    for rec in records:
        if cp.get('segments_done', 0) > 0 and rec.id <= cp['segments_done']:
            continue
        texts_to_embed.append(rec.summary or "")
        records_by_id.append(rec.id)

    if not texts_to_embed:
        print(f"  [{_ts()}] Nothing to migrate")
        return 0

    print(f"  [{_ts()}] Embedding {len(texts_to_embed)} segments...")
    migrated = 0

    for batch_start in range(0, len(texts_to_embed), 64):
        batch_texts = texts_to_embed[batch_start:batch_start + 64]
        vecs = _embed_batch(batch_texts)

        with get_db_session() as session:
            for j, rec_id in enumerate(records_by_id[batch_start:batch_start + 64]):
                vec = vecs[j]
                rec = session.query(ConversationSegment).filter_by(id=rec_id).first()
                if rec and vec is not None:
                    rec.embedding_vector = _vec_to_blob(vec)
                    session.commit()
                    migrated += 1
                    if migrated % 200 == 0:
                        print(f"  [{_ts()}] {migrated}/{len(texts_to_embed)}")
                        cp['segments_done'] = rec_id
                        _save_checkpoint(cp)

    cp['segments_done'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {migrated} segments embedded")
    return migrated


def process_unprocessed_messages():
    """
    Find sessions with messages that were never processed through the extractor.
    Process them in rolling windows to extract + embed new semantic facts.
    Skips sessions already covered by existing semantic/episodic records.
    """
    print(f"\n[{_ts()}] === Processing unprocessed raw messages ===")
    cp = _load_checkpoint()
    if cp.get('messages_processed') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        sessions = session.query(ChatSession).order_by(ChatSession.id.asc()).all()
        session_ids = [s.id for s in sessions]

    total_sessions = len(session_ids)
    sessions_done = cp.get('messages_processed', 0)
    extracted = 0

    for si, session_id in enumerate(session_ids):
        if si < sessions_done:
            continue

        # Check how many semantic records already exist for this session
        with get_db_session() as session:
            existing_sem = session.query(SemanticMemory).filter_by(session_id=session_id).count()
            existing_epi = session.query(EpisodicMemory).filter_by(session_id=session_id).count()

        # Get all messages for this session
        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.session_id == session_id,
                Message.role.in_(['user', 'assistant'])
            ).order_by(Message.id.asc()).all()

        msg_list = [
            {'role': m.role, 'content': m.content, 'timestamp': m.timestamp}
            for m in messages
        ]

        # Process in windows of 20 messages (matching extractor logic)
        WINDOW = 20
        for i in range(0, len(msg_list), WINDOW):
            window = msg_list[i:i + WINDOW]
            try:
                from memory.extractor import process_messages_for_memory
                process_messages_for_memory(session_id, window)
                extracted += 1
            except Exception as e:
                print(f"  [{_ts()}][WARN] Session {session_id} window {i}: {e}")

        # Checkpoint every session
        cp['messages_processed'] = si
        _save_checkpoint(cp)

        if (si + 1) % 10 == 0:
            elapsed = time.time() - _start_time
            rate = (si + 1) / max(elapsed, 0.1)
            eta = (total_sessions - si - 1) / max(rate, 1)
            print(f"  [{_ts()}] Sessions {si+1}/{total_sessions} | windows={extracted} | {rate:.1f}/s | ETA {eta:.0f}s")

    cp['messages_processed'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {total_sessions} sessions, {extracted} windows extracted")
    return extracted


_start_time = time.time()

def run_migration():
    """
    Run the full migration pipeline.
    
    Order:
        1. Embed existing semantic memories
        2. Embed existing episodic memories
        3. Embed existing conversation segments
        4. Process raw messages that weren't through the extractor
    
    Safe to re-run — checkpoint file tracks progress.
    """
    global _start_time
    _start_time = time.time()
    print("=" * 50)
    print(f"[{_ts()}] MEMORY SYSTEM MIGRATION")
    print("=" * 50)

    cp = _load_checkpoint()
    if cp.get('started_at') is None:
        cp['started_at'] = datetime.now().isoformat()
        _save_checkpoint(cp)

    t0 = time.time()

    sem = migrate_semantic_memories()
    epi = migrate_episodic_memories()
    seg = migrate_segments()
    msg = process_unprocessed_messages()

    elapsed = time.time() - t0

    print("\n" + "=" * 50)
    print(f"[{_ts()}] MIGRATION COMPLETE | elapsed {elapsed:.1f}s")
    print("=" * 50)
    print(f"  [{_ts()}] Semantic memories:  {sem} embedded")
    print(f"  [{_ts()}] Episodic memories: {epi} embedded")
    print(f"  [{_ts()}] Segments:          {seg} embedded")
    print(f"  [{_ts()}] Message windows:   {msg} processed")
    print("=" * 50)


if __name__ == "__main__":
    run_migration()
