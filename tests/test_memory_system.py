"""Tests for the structured memory system (Phases 1-7)."""

import sys
import os
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a test database
os.environ.setdefault('YUZU_DB_PATH', ':memory:')

import database
from database import (
    Base, get_engine, get_db_session, get_session_local,
    SemanticMemory, EpisodicMemory, ConversationSegment,
    Message, ChatSession, Profile,
)


def _reset_db():
    """Recreate all tables for a clean test slate."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # Re-create default profile/session like init_db does
    with get_db_session() as session:
        if session.query(Profile).count() == 0:
            profile = Profile(
                display_name='user',
                partner_name='Yuzu',
                affection=50,
            )
            session.add(profile)
            chat_session = ChatSession(
                name='New Chat',
                is_active=True,
            )
            session.add(chat_session)
            session.commit()


class TestPhase1DatabaseSchema(unittest.TestCase):
    """Phase 1: Verify new tables exist with correct columns."""

    @classmethod
    def setUpClass(cls):
        _reset_db()

    def test_semantic_memories_table_exists(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        tables = inspector.get_table_names()
        self.assertIn('semantic_memories', tables)

    def test_episodic_memories_table_exists(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        tables = inspector.get_table_names()
        self.assertIn('episodic_memories', tables)

    def test_conversation_segments_table_exists(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        tables = inspector.get_table_names()
        self.assertIn('conversation_segments', tables)

    def test_semantic_columns(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        cols = [c['name'] for c in inspector.get_columns('semantic_memories')]
        for col in ['id', 'session_id', 'entity', 'relation', 'target',
                     'confidence', 'importance', 'last_accessed', 'access_count',
                     'created_at']:
            self.assertIn(col, cols)

    def test_episodic_columns(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        cols = [c['name'] for c in inspector.get_columns('episodic_memories')]
        for col in ['id', 'session_id', 'summary', 'embedding', 'importance',
                     'emotional_weight', 'last_accessed', 'access_count',
                     'created_at']:
            self.assertIn(col, cols)

    def test_segment_columns(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        cols = [c['name'] for c in inspector.get_columns('conversation_segments')]
        for col in ['id', 'session_id', 'start_message_id', 'end_message_id',
                     'summary', 'embedding', 'importance', 'created_at']:
            self.assertIn(col, cols)

    def test_existing_messages_table_unchanged(self):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(get_engine())
        tables = inspector.get_table_names()
        self.assertIn('messages', tables)
        cols = [c['name'] for c in inspector.get_columns('messages')]
        for col in ['id', 'session_id', 'role', 'content', 'timestamp']:
            self.assertIn(col, cols)


class TestPhase2Extractor(unittest.TestCase):
    """Phase 2: Semantic extraction and episodic creation."""

    @classmethod
    def setUpClass(cls):
        _reset_db()

    def test_extract_preference(self):
        from memory.extractor import extract_semantic_facts
        msgs = [{'role': 'user', 'content': 'I prefer dark mode'}]
        facts = extract_semantic_facts(msgs)
        self.assertTrue(len(facts) >= 1)
        self.assertEqual(facts[0]['entity'], 'User')
        self.assertEqual(facts[0]['relation'], 'Prefers')
        self.assertIn('dark mode', facts[0]['target'])

    def test_extract_dislike(self):
        from memory.extractor import extract_semantic_facts
        msgs = [{'role': 'user', 'content': 'I hate loud music'}]
        facts = extract_semantic_facts(msgs)
        self.assertTrue(len(facts) >= 1)
        self.assertEqual(facts[0]['relation'], 'Dislikes')

    def test_extract_identity(self):
        from memory.extractor import extract_semantic_facts
        msgs = [{'role': 'user', 'content': "I'm a software developer"}]
        facts = extract_semantic_facts(msgs)
        self.assertTrue(len(facts) >= 1)
        self.assertEqual(facts[0]['relation'], 'Is')

    def test_extract_ignores_assistant_messages(self):
        from memory.extractor import extract_semantic_facts
        msgs = [{'role': 'assistant', 'content': 'I prefer chocolate'}]
        facts = extract_semantic_facts(msgs)
        self.assertEqual(len(facts), 0)

    def test_extract_indonesian_preference(self):
        from memory.extractor import extract_semantic_facts
        msgs = [{'role': 'user', 'content': 'aku lebih suka jawaban singkat'}]
        facts = extract_semantic_facts(msgs)
        self.assertTrue(len(facts) >= 1)
        self.assertEqual(facts[0]['relation'], 'Prefers')

    def test_emotional_weight_calculation(self):
        from memory.extractor import calculate_emotional_weight
        msgs = [
            {'role': 'user', 'content': 'I am so angry and frustrated!'},
            {'role': 'assistant', 'content': 'I understand you are upset.'},
        ]
        weight = calculate_emotional_weight(msgs)
        self.assertGreater(weight, 0.0)

    def test_emotional_weight_zero_for_neutral(self):
        from memory.extractor import calculate_emotional_weight
        msgs = [{'role': 'user', 'content': 'Hello, how are you?'}]
        weight = calculate_emotional_weight(msgs)
        self.assertEqual(weight, 0.0)

    def test_should_create_episodic_emotional(self):
        from memory.extractor import should_create_episodic
        msgs = [
            {'role': 'user', 'content': 'I am so angry and frustrated!'},
            {'role': 'user', 'content': 'I hate everything right now!'},
            {'role': 'user', 'content': 'This makes me so sad and upset!'},
        ]
        self.assertTrue(should_create_episodic(msgs))

    def test_should_create_episodic_long_conversation(self):
        from memory.extractor import should_create_episodic
        msgs = [{'role': 'user', 'content': f'Message {i}'} for i in range(12)]
        self.assertTrue(should_create_episodic(msgs))

    def test_should_create_episodic_affection_delta(self):
        from memory.extractor import should_create_episodic
        msgs = [{'role': 'user', 'content': 'Hi'}]
        self.assertTrue(should_create_episodic(msgs, affection_delta=25))

    def test_should_not_create_episodic_neutral(self):
        from memory.extractor import should_create_episodic
        msgs = [{'role': 'user', 'content': 'Hi'}]
        self.assertFalse(should_create_episodic(msgs, affection_delta=0))

    def test_upsert_semantic_memory_insert(self):
        from memory.extractor import upsert_semantic_memory
        _reset_db()
        upsert_semantic_memory(1, 'User', 'Prefers', 'dark mode')
        with get_db_session() as session:
            mem = session.query(SemanticMemory).filter_by(target='dark mode').first()
            self.assertIsNotNone(mem)
            self.assertEqual(mem.confidence, 0.5)

    def test_upsert_semantic_memory_update(self):
        from memory.extractor import upsert_semantic_memory
        _reset_db()
        upsert_semantic_memory(1, 'User', 'Prefers', 'dark mode')
        upsert_semantic_memory(1, 'User', 'Prefers', 'dark mode')
        with get_db_session() as session:
            mem = session.query(SemanticMemory).filter_by(target='dark mode').first()
            self.assertGreater(mem.confidence, 0.5)
            self.assertEqual(mem.access_count, 2)

    def test_create_episodic_memory(self):
        from memory.extractor import create_episodic_memory
        _reset_db()
        create_episodic_memory(1, 'User discussed dark mode preferences', 0.3, 0.6)
        with get_db_session() as session:
            mem = session.query(EpisodicMemory).first()
            self.assertIsNotNone(mem)
            self.assertIn('dark mode', mem.summary)


class TestPhase3Segmenter(unittest.TestCase):
    """Phase 3: Conversation segmentation."""

    def setUp(self):
        _reset_db()

    def _add_messages(self, session_id, count, time_base=None):
        """Add test messages to the DB."""
        if time_base is None:
            time_base = datetime.now()
        with get_db_session() as session:
            for i in range(count):
                ts = (time_base + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
                role = 'user' if i % 2 == 0 else 'assistant'
                msg = Message(
                    session_id=session_id,
                    role=role,
                    content=f'Message {i}',
                    content_encrypted=False,
                    timestamp=ts,
                )
                session.add(msg)
            session.commit()

    def test_segment_creates_segments(self):
        from memory.segmenter import segment_session
        self._add_messages(1, 25)
        count = segment_session(1)
        self.assertGreaterEqual(count, 1)

    def test_segment_no_overlaps(self):
        from memory.segmenter import segment_session
        self._add_messages(1, 50)
        segment_session(1)
        with get_db_session() as session:
            segments = session.query(ConversationSegment).filter_by(
                session_id=1
            ).order_by(ConversationSegment.start_message_id.asc()).all()
            for i in range(1, len(segments)):
                self.assertGreater(
                    segments[i].start_message_id,
                    segments[i - 1].end_message_id,
                )

    def test_segment_summaries_stored(self):
        from memory.segmenter import segment_session
        self._add_messages(1, 25)
        segment_session(1)
        with get_db_session() as session:
            seg = session.query(ConversationSegment).first()
            self.assertIsNotNone(seg)
            self.assertTrue(len(seg.summary) > 0)

    def test_segment_empty_session(self):
        from memory.segmenter import segment_session
        count = segment_session(999)
        self.assertEqual(count, 0)

    def test_time_gap_creates_new_segment(self):
        from memory.segmenter import segment_session
        base = datetime.now()
        # First batch
        self._add_messages(1, 8, time_base=base)
        # Second batch with 20-minute gap
        self._add_messages(1, 8, time_base=base + timedelta(minutes=30))
        count = segment_session(1)
        self.assertGreaterEqual(count, 2)


class TestPhase4Retrieval(unittest.TestCase):
    """Phase 4: Retrieval pipeline."""

    def setUp(self):
        _reset_db()

    def test_retrieve_semantic_memories(self):
        from memory.retrieval import retrieve_semantic_memories
        from memory.extractor import upsert_semantic_memory
        upsert_semantic_memory(1, 'User', 'Prefers', 'dark mode')
        upsert_semantic_memory(1, 'User', 'Uses', 'Python')
        result = retrieve_semantic_memories(1, limit=15)
        self.assertEqual(len(result), 2)
        self.assertIn('entity', result[0])

    def test_retrieve_episodic_memories(self):
        from memory.retrieval import retrieve_episodic_memories
        from memory.extractor import create_episodic_memory
        create_episodic_memory(1, 'First conversation', 0.5, 0.8)
        create_episodic_memory(1, 'Second conversation', 0.2, 0.5)
        result = retrieve_episodic_memories(1, limit=5)
        self.assertEqual(len(result), 2)
        # Higher importance should come first
        self.assertGreaterEqual(result[0]['score'], result[1]['score'])

    def test_retrieve_memory_bundle(self):
        from memory.retrieval import retrieve_memory
        result = retrieve_memory(1)
        self.assertIn('semantic', result)
        self.assertIn('episodic', result)
        self.assertIn('segments', result)

    def test_format_memory_with_data(self):
        from memory.retrieval import format_memory
        bundle = {
            'semantic': [
                {'entity': 'User', 'relation': 'Prefers', 'target': 'concise answers'},
            ],
            'episodic': [
                {'summary': 'User was frustrated during debugging'},
            ],
            'segments': [
                {'summary': 'Discussion about image caching'},
            ],
        }
        text = format_memory(bundle)
        self.assertIn('Known preferences', text)
        self.assertIn('concise answers', text)
        self.assertIn('Recent important events', text)
        self.assertIn('Relevant past context', text)

    def test_format_memory_empty(self):
        from memory.retrieval import format_memory
        bundle = {'semantic': [], 'episodic': [], 'segments': []}
        text = format_memory(bundle)
        self.assertEqual(text, '')

    def test_retrieval_under_100ms(self):
        """Retrieval should be fast even with data."""
        import time
        from memory.retrieval import retrieve_memory
        from memory.extractor import upsert_semantic_memory, create_episodic_memory
        for i in range(20):
            upsert_semantic_memory(1, 'User', 'Prefers', f'item_{i}')
        for i in range(10):
            create_episodic_memory(1, f'Event {i}', 0.3, 0.5)
        start = time.time()
        retrieve_memory(1)
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1, f"Retrieval took {elapsed:.3f}s, expected < 0.1s")


class TestPhase6ReviewDecay(unittest.TestCase):
    """Phase 6: FSRS-style review and decay."""

    def setUp(self):
        _reset_db()

    def test_decay_reduces_importance(self):
        from memory.review import decay_semantic_memories
        # Insert with old last_accessed
        with get_db_session() as session:
            mem = SemanticMemory(
                session_id=1,
                entity='User',
                relation='Prefers',
                target='test',
                confidence=0.5,
                importance=0.8,
                last_accessed=datetime.now() - timedelta(days=30),
                access_count=0,
            )
            session.add(mem)
            session.commit()

        decay_semantic_memories(session_id=1)

        with get_db_session() as session:
            mem = session.query(SemanticMemory).first()
            self.assertLess(mem.importance, 0.8)

    def test_frequently_accessed_decays_slower(self):
        from memory.review import decay_semantic_memories
        with get_db_session() as session:
            low_access = SemanticMemory(
                session_id=1, entity='User', relation='Prefers', target='low',
                confidence=0.5, importance=0.8,
                last_accessed=datetime.now() - timedelta(days=7),
                access_count=0,
            )
            high_access = SemanticMemory(
                session_id=1, entity='User', relation='Prefers', target='high',
                confidence=0.5, importance=0.8,
                last_accessed=datetime.now() - timedelta(days=7),
                access_count=20,
            )
            session.add_all([low_access, high_access])
            session.commit()

        decay_semantic_memories(session_id=1)

        with get_db_session() as session:
            low = session.query(SemanticMemory).filter_by(target='low').first()
            high = session.query(SemanticMemory).filter_by(target='high').first()
            self.assertGreater(high.importance, low.importance)

    def test_reinforce_increases_importance(self):
        from memory.review import reinforce_memory
        with get_db_session() as session:
            mem = SemanticMemory(
                session_id=1, entity='User', relation='Prefers', target='test',
                confidence=0.5, importance=0.5,
                last_accessed=datetime.now(), access_count=0,
            )
            session.add(mem)
            session.commit()
            mem_id = mem.id

        reinforce_memory(mem_id, 'semantic')

        with get_db_session() as session:
            mem = session.query(SemanticMemory).first()
            self.assertGreater(mem.importance, 0.5)
            self.assertEqual(mem.access_count, 1)

    def test_run_decay_no_crash(self):
        from memory.review import run_decay
        run_decay()  # Should not crash even with empty DB
        run_decay(session_id=999)


class TestPhase7Migration(unittest.TestCase):
    """Phase 7: Migration and fallback safety."""

    def setUp(self):
        _reset_db()

    def test_migrate_session_extracts_facts(self):
        from memory.migrate_history import migrate_session
        with get_db_session() as session:
            for i in range(5):
                msg = Message(
                    session_id=1,
                    role='user' if i % 2 == 0 else 'assistant',
                    content='I prefer dark mode' if i == 0 else f'Reply {i}',
                    content_encrypted=False,
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )
                session.add(msg)
            session.commit()

        result = migrate_session(1)
        self.assertGreaterEqual(result['semantic_count'], 1)

    def test_memory_retrieval_fallback(self):
        """If memory retrieval fails, it should not crash."""
        from memory.retrieval import retrieve_memory
        result = retrieve_memory(session_id=99999)
        self.assertIn('semantic', result)
        self.assertEqual(len(result['semantic']), 0)


if __name__ == '__main__':
    unittest.main()
