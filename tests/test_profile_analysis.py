
from __future__ import annotations

from app.profile_analysis import (
    detect_important_content,
    merge_and_clean_memory,
    normalize_memory_item,
    parse_global_profile_summary,
)


class TestNormalizeMemoryItem:
    def test_lowercases(self):
        assert normalize_memory_item("COFFEE") == "coffee"

    def test_strips_whitespace(self):
        assert normalize_memory_item("  coffee  ") == "coffee"

    def test_collapses_internal_spaces(self):
        assert normalize_memory_item("hot   black   coffee") == "hot black coffee"

    def test_strips_trailing_punct(self):
        assert normalize_memory_item("coffee.") == "coffee"
        assert normalize_memory_item('coffee"') == "coffee"
        assert normalize_memory_item("coffee'") == "coffee"
        assert normalize_memory_item("coffee,") == "coffee"


class TestMergeAndCleanMemory:
    def test_dedupes_against_existing(self):
        merged = merge_and_clean_memory(["coffee"], ["Coffee.", "tea"], 10)
        assert merged == ["coffee", "tea"]

    def test_preserves_first_occurrence_text(self):
        merged = merge_and_clean_memory([], ["COFFEE", "coffee"], 10)
        assert merged == ["COFFEE"]

    def test_enforces_max_size(self):
        merged = merge_and_clean_memory(["a", "b"], ["c", "d"], 3)
        assert merged == ["a", "b", "c"]

    def test_skips_empty_items(self):
        merged = merge_and_clean_memory(["", "  "], ["x", None], 10)  # type: ignore[list-item]
        assert merged == ["x"]


class TestDetectImportantContent:
    def test_matches_keyword(self):
        assert detect_important_content("please remember this")
        assert detect_important_content("I LOVE this")

    def test_no_match(self):
        assert not detect_important_content("hello there")


class TestParseGlobalProfileSummary:
    SAMPLE = """Player Summary: A curious developer.

Likes: coffee, late nights, refactoring

Dislikes: meetings, regressions

Personality Traits: focused, introverted

Important Memories: shipped first PR, fixed prod incident

Relationship Dynamics: trusts the AI for technical guidance."""

    def test_parses_summary(self):
        result = parse_global_profile_summary(self.SAMPLE)
        assert result["player_summary"] == "A curious developer"
        assert result["relationship_dynamics"].startswith("trusts the AI")

    def test_parses_key_facts(self):
        result = parse_global_profile_summary(self.SAMPLE)
        assert result["key_facts"]["likes"] == ["coffee", "late nights", "refactoring"]
        assert result["key_facts"]["dislikes"] == ["meetings", "regressions"]
        assert result["key_facts"]["personality_traits"] == ["focused", "introverted"]
        assert result["key_facts"]["important_memories"] == [
            "shipped first PR",
            "fixed prod incident",
        ]

    def test_handles_empty_input(self):
        result = parse_global_profile_summary("")
        assert result["player_summary"] == ""
        assert all(v == [] for v in result["key_facts"].values())

    def test_handles_missing_sections(self):
        result = parse_global_profile_summary("Player Summary: Just a name.")
        assert result["player_summary"] == "Just a name"
        assert result["key_facts"]["likes"] == []

    def test_dedupes_key_facts(self):
        text = "Likes: coffee, coffee, tea"
        result = parse_global_profile_summary(text)
        assert result["key_facts"]["likes"] == ["coffee", "tea"]
