from __future__ import annotations

from app.db import (
    DEFAULT_PROFILE_PARAMS,
    build_encryption_status,
    build_profile_update,
    format_ai_history_rows,
    format_conversation_summary,
    parse_event_row,
    parse_global_knowledge_row,
    parse_json,
    parse_message_row,
    parse_profile_row,
    parse_session_row,
)


class TestParseJson:
    def test_empty_input_returns_dict(self):
        assert parse_json(None) == {}
        assert parse_json("") == {}

    def test_valid_json(self):
        assert parse_json('{"a": 1}') == {"a": 1}

    def test_invalid_json_returns_dict(self):
        assert parse_json("not json") == {}

    def test_already_dict_passes_through(self):
        # Tolerate the case where the column already deserialized.
        assert parse_json({"a": 1}) == {"a": 1}  # type: ignore[arg-type]


class TestProfileParsers:
    def test_parse_profile_row_empty(self):
        assert parse_profile_row(None) == {}
        assert parse_profile_row({}) == {}

    def test_parse_profile_row_full(self):
        row = {
            "id": 1,
            "user_name": "Bani",
            "partner_name": "Yuzu",
            "affection": 75,
            "theme": "dark",
            "session_history": {},
            "providers_config": {"preferred_provider": "chutes"},
            "context": "{}",
            "image_model": "qwen_image",
            "vision_model": "kimi-k2.5",
            "created_at": None,
            "updated_at": None,
        }
        out = parse_profile_row(row)
        assert out["user_name"] == "Bani"
        assert out["affection"] == 75
        assert out["providers_config"] == {"preferred_provider": "chutes"}

    def test_parse_profile_row_uses_defaults_for_missing(self):
        out = parse_profile_row({"id": 7})
        assert out["user_name"] == ""
        assert out["affection"] == 50
        assert out["theme"] == "default"


class TestBuildProfileUpdate:
    def test_returns_none_for_empty_or_unknown(self):
        assert build_profile_update({}) is None
        assert build_profile_update({"unknown": "x"}) is None

    def test_text_field(self):
        result = build_profile_update({"user_name": "new"})
        assert result is not None
        query, params = result
        assert "user_name = %s" in query
        assert "updated_at = %s" in query
        assert params[0] == "new"

    def test_global_knowledge_is_not_a_profile_field(self):
        assert build_profile_update({"global_knowledge": {"facts": []}}) is None

    def test_affection_coerced_to_int(self):
        result = build_profile_update({"affection": "99"})
        assert result is not None
        _, params = result
        assert params[0] == 99

    def test_default_profile_params_match_columns(self):
        # 7 values before timestamp/updated_at (datetimes added by caller at insert time)
        assert len(DEFAULT_PROFILE_PARAMS) == 7


class TestSessionParsers:
    def test_parse_session_row_empty(self):
        assert parse_session_row(None) == {}

    def test_parse_session_row_defaults(self):
        out = parse_session_row({"id": 3})
        assert out["name"] == "New Chat"
        assert out["is_active"] is False
        assert out["message_count"] == 0


class TestMessageParsers:
    def test_parse_message_row(self):
        row = {
            "id": 1,
            "session_id": 2,
            "role": "user",
            "content": "hi",
            "timestamp": "2026-01-01 00:00:00",
        }
        out = parse_message_row(row)
        assert out["id"] == 1
        assert out["role"] == "user"
        assert out["content"] == "hi"
        assert out["timestamp"] == "2026-01-01 00:00:00"

    def test_parse_event_row(self):
        row = {"content": "connected", "timestamp": None}
        assert parse_event_row(row) == {"content": "connected", "timestamp": "None"}

    def test_format_conversation_summary_truncates(self):
        long = "x" * 250
        rows = [{"role": "user", "content": long}]
        out = format_conversation_summary(rows)
        assert out.startswith("User: ")
        assert out.endswith("...")
        assert len(out) < len(long)

    def test_format_conversation_summary_speakers(self):
        rows = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        out = format_conversation_summary(rows)
        assert out == "User: hi\nAI: hello"


class TestFormatAiHistoryRows:
    def test_skips_event_log_rows(self):
        rows = [{"role": "event_log", "content": "x", "timestamp": ""}]
        assert format_ai_history_rows(rows) == []

    def test_user_row_gets_timestamp_appended(self):
        rows = [{"role": "user", "content": "hi", "timestamp": "2026-01-01 12:00:00"}]
        out = format_ai_history_rows(rows)
        assert out[0]["role"] == "user"
        assert out[0]["content"].startswith("hi ")
        assert "[2026-01-01 12:00:00]" in out[0]["content"]

    def test_assistant_passes_through(self):
        rows = [{"role": "assistant", "content": "hello", "timestamp": ""}]
        assert format_ai_history_rows(rows) == [
            {"role": "assistant", "content": "hello"}
        ]

    def test_tool_role_passes_through(self):
        contract = (
            "<details><summary>image_tools</summary>\n"
            "```bash\n$ /imagine cat\n```\n"
            "image_url\n"
            "</details>"
        )
        rows = [{"role": "image_tools", "content": contract, "timestamp": ""}]
        out = format_ai_history_rows(rows)
        assert len(out) == 1
        # Tool roles are normalized to OpenAI "tool" format
        assert out[0]["role"] == "tool"
        assert out[0]["content"] == contract

    def test_native_fc_tool_call_includes_turn_id(self):
        """FC4: Native FC assistant messages preserve tool_calls + turn_id."""
        rows = [
            {
                "id": 1,
                "session_id": "s1",
                "role": "assistant",
                "content": "",
                "image_paths": "[]",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "bash", "arguments": "{}"}}
                ],
                "tool_call_id": None,
                "turn_id": "turn_abc",
                "timestamp": "2026-01-01",
            }
        ]
        out = format_ai_history_rows(rows)
        assert len(out) == 1
        assert out[0]["role"] == "assistant"
        assert "tool_calls" in out[0]
        assert out[0]["turn_id"] == "turn_abc"

    def test_native_fc_tool_result_includes_turn_id(self):
        """FC4: Native FC tool results preserve tool_call_id + turn_id."""
        rows = [
            {
                "id": 2,
                "session_id": "s1",
                "role": "tool",
                "content": "output",
                "image_paths": "[]",
                "tool_calls": None,
                "tool_call_id": "call_1",
                "turn_id": "turn_abc",
                "timestamp": "2026-01-01",
            }
        ]
        out = format_ai_history_rows(rows)
        assert len(out) == 1
        assert out[0]["role"] == "tool"
        assert out[0]["tool_call_id"] == "call_1"
        assert out[0]["turn_id"] == "turn_abc"


class TestEncryptionStatus:
    def test_build_encryption_status_with_all_none(self):
        out = build_encryption_status(None, None)
        assert out["messages"]["total"] == 0

    def test_build_encryption_status_populated(self):
        out = build_encryption_status({"cnt": 100}, {"cnt": 5})
        assert out["messages"] == {
            "total": 100,
            "encrypted": 5,
            "policy": "NO_ENCRYPTION",
        }


def test_parse_global_knowledge_row():
    row = {
        "id": "00000000-0000-7000-8000-000000000001",
        "category": "Identity",
        "content": "Bani",
        "sort_order": 2,
        "enabled": 1,
        "created_at": None,
        "updated_at": None,
    }
    out = parse_global_knowledge_row(row)
    assert out == {
        "id": "00000000-0000-7000-8000-000000000001",
        "category": "Identity",
        "content": "Bani",
        "sort_order": 2,
        "enabled": True,
        "created_at": None,
        "updated_at": None,
    }
