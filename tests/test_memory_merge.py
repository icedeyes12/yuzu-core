"""Tests for global memory normalization, deduplication, and merge logic."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import normalize_memory_item, merge_and_clean_memory, _merge_profile_data


class TestNormalizeMemoryItem(unittest.TestCase):
    """Tests for normalize_memory_item()."""

    def test_lowercase(self):
        self.assertEqual(normalize_memory_item("Feeling Emotionally Safe"), "feeling emotionally safe")

    def test_strip_whitespace(self):
        self.assertEqual(normalize_memory_item("  hello world  "), "hello world")

    def test_remove_trailing_period(self):
        self.assertEqual(normalize_memory_item("feeling emotionally safe."), "feeling emotionally safe")

    def test_remove_trailing_comma(self):
        self.assertEqual(normalize_memory_item("feeling emotionally safe,"), "feeling emotionally safe")

    def test_remove_trailing_quote(self):
        self.assertEqual(normalize_memory_item("feeling emotionally safe\""), "feeling emotionally safe")

    def test_remove_trailing_single_quote(self):
        self.assertEqual(normalize_memory_item("feeling emotionally safe'"), "feeling emotionally safe")

    def test_collapse_multiple_spaces(self):
        self.assertEqual(normalize_memory_item("feeling   emotionally   safe"), "feeling emotionally safe")

    def test_combined_normalization(self):
        self.assertEqual(normalize_memory_item(" Feeling emotionally safe. "), "feeling emotionally safe")

    def test_inner_punctuation_preserved(self):
        self.assertEqual(normalize_memory_item("Being called 'Bas'"), "being called 'bas")

    def test_empty_string(self):
        self.assertEqual(normalize_memory_item(""), "")

    def test_only_whitespace(self):
        self.assertEqual(normalize_memory_item("   "), "")


class TestMergeAndCleanMemory(unittest.TestCase):
    """Tests for merge_and_clean_memory()."""

    def test_acceptance_test_from_issue(self):
        """The exact acceptance test from the problem statement."""
        existing = ["Feeling emotionally safe"]
        new_items = ["feeling emotionally safe", "feeling emotionally safe.", " Being called 'Bas' "]
        result = merge_and_clean_memory(existing, new_items, max_size=30)
        self.assertEqual(result, ["Feeling emotionally safe", " Being called 'Bas' "])

    def test_no_duplicates_added(self):
        existing = ["apples", "bananas"]
        new_items = ["Apples", "BANANAS", "cherries"]
        result = merge_and_clean_memory(existing, new_items, max_size=30)
        self.assertEqual(result, ["apples", "bananas", "cherries"])

    def test_preserves_first_occurrence(self):
        existing = ["Hello World"]
        new_items = ["hello world"]
        result = merge_and_clean_memory(existing, new_items, max_size=30)
        self.assertEqual(result, ["Hello World"])

    def test_order_preserved(self):
        existing = ["a", "b", "c"]
        new_items = ["d", "e"]
        result = merge_and_clean_memory(existing, new_items, max_size=30)
        self.assertEqual(result, ["a", "b", "c", "d", "e"])

    def test_max_size_enforced(self):
        existing = ["item1", "item2", "item3"]
        new_items = ["item4", "item5"]
        result = merge_and_clean_memory(existing, new_items, max_size=4)
        self.assertEqual(result, ["item1", "item2", "item3", "item4"])

    def test_keeps_earliest_on_overflow(self):
        existing = [f"item{i}" for i in range(10)]
        new_items = [f"new{i}" for i in range(10)]
        result = merge_and_clean_memory(existing, new_items, max_size=15)
        self.assertEqual(len(result), 15)
        self.assertEqual(result[:10], [f"item{i}" for i in range(10)])
        self.assertEqual(result[10:], [f"new{i}" for i in range(5)])

    def test_empty_existing_list(self):
        result = merge_and_clean_memory([], ["a", "b"], max_size=30)
        self.assertEqual(result, ["a", "b"])

    def test_empty_new_items(self):
        result = merge_and_clean_memory(["a", "b"], [], max_size=30)
        self.assertEqual(result, ["a", "b"])

    def test_both_empty(self):
        result = merge_and_clean_memory([], [], max_size=30)
        self.assertEqual(result, [])

    def test_skips_empty_strings(self):
        result = merge_and_clean_memory(["a"], ["", "  ", "b"], max_size=30)
        self.assertEqual(result, ["a", "b"])

    def test_dedup_within_existing_list(self):
        existing = ["hello", "Hello", "HELLO"]
        result = merge_and_clean_memory(existing, [], max_size=30)
        self.assertEqual(result, ["hello"])

    def test_trailing_punctuation_dedup(self):
        existing = ["feeling safe"]
        new_items = ["feeling safe.", "feeling safe,", "feeling safe\""]
        result = merge_and_clean_memory(existing, new_items, max_size=30)
        self.assertEqual(result, ["feeling safe"])


class TestMergeProfileData(unittest.TestCase):
    """Tests for _merge_profile_data() integration."""

    def test_merges_key_facts_without_duplicates(self):
        existing = {
            'player_summary': 'test summary',
            'key_facts': {
                'likes': ['Feeling emotionally safe', 'music'],
                'dislikes': ['being ignored'],
                'personality_traits': ['kind'],
                'important_memories': ['first meeting'],
            },
            'relationship_dynamics': 'good',
        }
        new_data = {
            'key_facts': {
                'likes': ['feeling emotionally safe', 'gaming'],
                'dislikes': ['Being Ignored', 'loud noises'],
                'personality_traits': ['Kind', 'creative'],
                'important_memories': ['First meeting.', 'birthday'],
            },
        }
        result = _merge_profile_data(existing, new_data)
        self.assertEqual(result['key_facts']['likes'], ['Feeling emotionally safe', 'music', 'gaming'])
        self.assertEqual(result['key_facts']['dislikes'], ['being ignored', 'loud noises'])
        self.assertEqual(result['key_facts']['personality_traits'], ['kind', 'creative'])
        self.assertEqual(result['key_facts']['important_memories'], ['first meeting', 'birthday'])

    def test_enforces_list_limits(self):
        existing = {
            'key_facts': {
                'likes': [f'like{i}' for i in range(28)],
                'dislikes': [],
                'personality_traits': [f'trait{i}' for i in range(14)],
                'important_memories': [],
            },
        }
        new_data = {
            'key_facts': {
                'likes': [f'newlike{i}' for i in range(10)],
                'dislikes': [],
                'personality_traits': [f'newtrait{i}' for i in range(5)],
                'important_memories': [],
            },
        }
        result = _merge_profile_data(existing, new_data)
        self.assertLessEqual(len(result['key_facts']['likes']), 30)
        self.assertLessEqual(len(result['key_facts']['personality_traits']), 15)

    def test_returns_new_data_when_existing_empty(self):
        new_data = {
            'key_facts': {
                'likes': ['a'],
                'dislikes': [],
                'personality_traits': [],
                'important_memories': [],
            },
        }
        result = _merge_profile_data({}, new_data)
        self.assertEqual(result['key_facts']['likes'], ['a'])


if __name__ == '__main__':
    unittest.main()
