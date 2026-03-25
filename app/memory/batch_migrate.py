# [FILE: memory/batch_migrate.py]
# [DESCRIPTION: Batch migration script for backfilling embeddings on existing memory records]
# [USAGE: python -c "from app.memory.batch_migrate import run_migration; run_migration()"]

import os
import json
import time
import struct
from datetime import datetime
from app.database import get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment, Message, ChatSession
from app.memory.embedder import embed_texts


CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), 'migration_checkpoint.json')
_start_time = time.time()

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
    for attempt in range(retries):
        try:
            return embed_texts(texts)
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [{_ts()}] [RETRY] Embed batch failed (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    return [None] * len(texts)


def migrate_semantic_memories():
    print(f"\n[{_ts()}] === Migrating semantic_memories ===")
    cp = _load_checkpoint()
    if cp.get('semantic_done') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        records = session.query(SemanticMemory).order_by(SemanticMemory.id.asc()).all()
        items = [{'id': r.id, 'text': f"{r.entity} {r.relation} {r.target}"} for r in records]

    if not items:
        print(f"  [{_ts()}] Nothing to migrate")
        return 0

    items_to_process = items[cp.get('semantic_done', 0):]
    print(f"  [{_ts()}] Embedding {len(items_to_process)} semantic records...")

    migrated = 0

    for batch_start in range(0, len(items_to_process), 64):
        batch = items_to_process[batch_start:batch_start + 64]
        batch_texts = [item['text'] for item in batch]
        vecs = _embed_batch(batch_texts)

        with get_db_session() as session:
            for j, item in enumerate(batch):
                vec = vecs[j]
                rec = session.query(SemanticMemory).filter_by(id=item['id']).first()
                if rec and vec is not None:
                    rec.embedding_vector = _vec_to_blob(vec)
                    session.commit()
                    migrated += 1

        if (batch_start + 64) % 500 == 0 or (batch_start + 64) >= len(items_to_process):
            elapsed = time.time() - _start_time
            done = cp['semantic_done'] + batch_start + 64
            rate = done / max(elapsed, 0.1)
            eta = (len(items) - done) / max(rate, 0.1)
            print(f"  [{_ts()}] {done}/{len(items)} | {rate:.1f}/s | ETA {eta:.0f}s")
            cp['semantic_done'] = cp['semantic_done'] + batch_start + 64
            _save_checkpoint(cp)

    cp['semantic_done'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {migrated} semantic memories embedded")
    return migrated


def migrate_episodic_memories():
    print(f"\n[{_ts()}] === Migrating episodic_memories ===")
    cp = _load_checkpoint()
    if cp.get('episodic_done') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        records = session.query(EpisodicMemory).order_by(EpisodicMemory.id.asc()).all()
        items = [{'id': r.id, 'text': r.summary or ""} for r in records]

    if not items:
        print(f"  [{_ts()}] Nothing to migrate")
        return 0

    items_to_process = items[cp.get('episodic_done', 0):]
    print(f"  [{_ts()}] Embedding {len(items_to_process)} episodic records...")

    migrated = 0

    for batch_start in range(0, len(items_to_process), 64):
        batch = items_to_process[batch_start:batch_start + 64]
        batch_texts = [item['text'] for item in batch]
        vecs = _embed_batch(batch_texts)

        with get_db_session() as session:
            for j, item in enumerate(batch):
                vec = vecs[j]
                rec = session.query(EpisodicMemory).filter_by(id=item['id']).first()
                if rec and vec is not None:
                    rec.embedding = _vec_to_blob(vec)
                    session.commit()
                    migrated += 1

        if (batch_start + 64) % 500 == 0 or (batch_start + 64) >= len(items_to_process):
            elapsed = time.time() - _start_time
            done = cp['episodic_done'] + batch_start + 64
            rate = done / max(elapsed, 0.1)
            eta = (len(items) - done) / max(rate, 0.1)
            print(f"  [{_ts()}] {done}/{len(items)} | {rate:.1f}/s | ETA {eta:.0f}s")
            cp['episodic_done'] = cp['episodic_done'] + batch_start + 64
            _save_checkpoint(cp)

    cp['episodic_done'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {migrated} episodic memories embedded")
    return migrated


def migrate_segments():
    print(f"\n[{_ts()}] === Migrating conversation_segments ===")
    cp = _load_checkpoint()
    if cp.get('segments_done') == -1:
        print(f"  [{_ts()}] Skipped (already complete)")
        return 0

    with get_db_session() as session:
        records = session.query(ConversationSegment).order_by(ConversationSegment.id.asc()).all()
        items = [{'id': r.id, 'text': r.summary or ""} for r in records]

    if not items:
        print(f"  [{_ts()}] Nothing to migrate")
        return 0

    items_to_process = items[cp.get('segments_done', 0):]
    print(f"  [{_ts()}] Embedding {len(items_to_process)} segments...")

    migrated = 0

    for batch_start in range(0, len(items_to_process), 64):
        batch = items_to_process[batch_start:batch_start + 64]
        batch_texts = [item['text'] for item in batch]
        vecs = _embed_batch(batch_texts)

        with get_db_session() as session:
            for j, item in enumerate(batch):
                vec = vecs[j]
                rec = session.query(ConversationSegment).filter_by(id=item['id']).first()
                if rec and vec is not None:
                    rec.embedding = _vec_to_blob(vec)  # NOTE: column is 'embedding', not 'embedding_vector'
                    session.commit()
                    migrated += 1

        if (batch_start + 64) % 500 == 0 or (batch_start + 64) >= len(items_to_process):
            elapsed = time.time() - _start_time
            done = cp['segments_done'] + batch_start + 64
            rate = done / max(elapsed, 0.1)
            eta = (len(items) - done) / max(rate, 0.1)
            print(f"  [{_ts()}] {done}/{len(items)} | {rate:.1f}/s | ETA {eta:.0f}s")
            cp['segments_done'] = cp['segments_done'] + batch_start + 64
            _save_checkpoint(cp)

    cp['segments_done'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: {migrated} segments embedded")
    return migrated


def process_unprocessed_messages():
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

        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.session_id == session_id,
                Message.role.in_(['user', 'assistant'])
            ).order_by(Message.id.asc()).all()
            msg_list = [
                {'role': m.role, 'content': m.content, 'timestamp': m.timestamp}
                for m in messages
            ]

        WINDOW = 20
        for i in range(0, len(msg_list), WINDOW):
            window = msg_list[i:i + WINDOW]
            try:
                from app.memory.extractor import process_messages_for_memory
                process_messages_for_memory(session_id, window)
                extracted += 1
            except Exception as e:
                print(f"  [{_ts()}] [WARN] Session {session_id} window {i}: {e}")

        cp['messages_processed'] = si + 1
        _save_checkpoint(cp)

        if (si + 1) % 10 == 0 or (si + 1) == total_sessions:
            elapsed = time.time() - _start_time
            rate = (si + 1) / max(elapsed, 0.1)
            remaining = total_sessions - si - 1
            eta = remaining / max(rate, 0.1)
            print(f"  [{_ts()}] Sessions {si+1}/{total_sessions} | windows={extracted} | {rate:.1f}/s | ETA {eta:.0f}s")

    cp['messages_processed'] = -1
    _save_checkpoint(cp)
    print(f"  [{_ts()}] Done: processed {total_sessions} sessions, {extracted} extraction windows")
    return extracted


def run_migration():
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
