# FILE: tests/test_db_queries.py
# DESCRIPTION: Tests for the pure helpers in app.db_queries.
#              These never touch the database.

from __future__ import annotations

from app.db import (
    ALL_TOOL_ROLES,
    DEFAULT_PROFILE_PARAMS,
    SCHEMA_DDL,
    TOOL_ROLES,
    build_encryption_status,
    build_profile_update,
    decrypt_api_key_rows,
    extract_command_from_markdown_contract,
    extract_raw_result_from_markdown_contract,
    format_ai_history_rows,
    format_conversation_summary,
    format_session_event,
    parse_event_row,
    parse_json,
    parse_message_row,
    parse_profile_row,
    parse_session_memory_rows,
    parse_session_row,
    tool_role_for,
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
            "display_name": "Bani",
            "partner_name": "Yuzu",
            "affection": 75,
            "theme": "dark",
            "memory_state": {"x": 1},
            "session_history": {},
            "global_knowledge": {},
            "providers_config": {"preferred_provider": "chutes"},
            "context": "{}",
            "image_model": "hunyuan",
            "vision_model": "kimi-k2.5",
            "created_at": None,
            "updated_at": None,
        }
        out = parse_profile_row(row)
        assert out["display_name"] == "Bani"
        assert out["affection"] == 75
        assert out["memory"] == {"x": 1}
        assert out["providers_config"] == {"preferred_provider": "chutes"}

    def test_parse_profile_row_uses_defaults_for_missing(self):
        out = parse_profile_row({"id": 7})
        assert out["display_name"] == ""
        assert out["affection"] == 50
        assert out["theme"] == "default"
        assert out["memory"] == {}


class TestBuildProfileUpdate:
    def test_returns_none_for_empty_or_unknown(self):
        assert build_profile_update({}) is None
        assert build_profile_update({"unknown": "x"}) is None

    def test_text_field(self):
        result = build_profile_update({"display_name": "new"})
        assert result is not None
        query, params = result
        assert "display_name = %s" in query
        assert "updated_at = %s" in query
        assert params[0] == "new"

    def test_json_field_serializes_dict(self):
        result = build_profile_update({"memory": {"a": 1}})
        assert result is not None
        query, params = result
        assert "memory_state = %s" in query
        assert params[0] == '{"a": 1}'

    def test_affection_coerced_to_int(self):
        result = build_profile_update({"affection": "99"})
        assert result is not None
        _, params = result
        assert params[0] == 99

    def test_default_profile_params_match_columns(self):
        # 9 placeholders before timestamp/updated_at
        assert len(DEFAULT_PROFILE_PARAMS) == 11


class TestSessionParsers:
    def test_parse_session_row_empty(self):
        assert parse_session_row(None) == {}

    def test_parse_session_row_defaults(self):
        out = parse_session_row({"id": 3})
        assert out["name"] == "New Chat"
        assert out["is_active"] is False
        assert out["message_count"] == 0
        assert out["memory"] == {}

    def test_parse_session_memory_rows_empty(self):
        assert parse_session_memory_rows([]) == {}

    def test_parse_session_memory_rows_populated(self):
        rows = [
            {"content": "hi", "role": "system", "timestamp": "2026-01-01"},
            {"content": "note", "role": "memory", "timestamp": "2026-01-02"},
        ]
        out = parse_session_memory_rows(rows)
        assert out["count"] == 2
        assert out["notes"][0]["content"] == "hi"


class TestApiKeyDecryption:
    def test_unencrypted_passes_through(self):
        rows = [
            {"key_name": "openrouter", "key_value": "sk-plain", "key_encrypted": False}
        ]
        out = decrypt_api_key_rows(rows)
        assert out == {"openrouter": "sk-plain"}

    def test_skips_rows_with_missing_name(self):
        rows = [{"key_name": None, "key_value": "sk", "key_encrypted": False}]
        out = decrypt_api_key_rows(rows)
        assert out == {}


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


class TestToolContractParsers:
    def test_extract_command_from_contract(self):
        contract = (
            "<details><summary>image_tools</summary>\n"
            "```bash\nuser@host$ /imagine a cat\n```\n"
            "result\n</details>"
        )
        extract_command_from_contract = extract_command_from_markdown_contract
        assert extract_command_from_contract(contract) == "/imagine a cat"

    def test_extract_command_returns_input_when_no_match(self):
        assert extract_command_from_markdown_contract("plain text") == "plain text"

    def test_extract_command_handles_empty(self):
        assert extract_command_from_markdown_contract("") == ""

    def test_extract_raw_result_strips_formatting(self):
        contract = (
            "<details><summary>x</summary>\n"
            "```bash\n$ /imagine cat\n```\n"
            "actual result\n"
            "</details>"
        )
        assert (
            extract_raw_result_from_markdown_contract(contract).strip()
            == "actual result"
        )

    def test_extract_raw_result_strips_html(self):
        assert (
            extract_raw_result_from_markdown_contract("<b>bold</b> text") == "bold text"
        )


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
        assert out[0]["role"] == "image_tools"
        assert out[0]["content"] == "image_url"


class TestEncryptionStatus:
    def test_build_encryption_status_with_all_none(self):
        out = build_encryption_status(None, None, None, None)
        assert out["messages"]["total"] == 0
        assert out["api_keys"]["encrypted"] == 0

    def test_build_encryption_status_populated(self):
        out = build_encryption_status({"cnt": 100}, {"cnt": 5}, {"cnt": 3}, {"cnt": 3})
        assert out["messages"] == {
            "total": 100,
            "encrypted": 5,
            "policy": "NO_ENCRYPTION",
        }
        assert out["api_keys"] == {
            "total": 3,
            "encrypted": 3,
            "policy": "FULL_ENCRYPTION",
        }


class TestToolRoleHelpers:
    def test_tool_role_for_known(self):
        assert tool_role_for("imagine") == "image_tools"
        assert tool_role_for("image_generate") == "image_tools"
        assert tool_role_for("request") == "request_tools"

    def test_tool_role_for_unknown_falls_back(self):
        assert tool_role_for("weather") == "weather_tools"

    def test_all_tool_roles_dedup(self):
        # imagine + image_generate both map to image_tools, dedup -> 2 unique
        assert sorted(ALL_TOOL_ROLES) == [
            "ask_rei_tools",
            "fs_tools",
            "image_tools",
            "memory_tools",
            "python_tools",
            "request_tools",
            "shell_tools",
            "sql_tools",
        ]

    def test_tool_roles_dict_is_complete(self):
        assert "imagine" in TOOL_ROLES
        assert "image_generate" in TOOL_ROLES
        assert "request" in TOOL_ROLES


class TestMisc:
    def test_format_session_event(self):
        assert format_session_event("hi", "web") == "*hi on web*"

    def test_schema_ddl_has_expected_tables(self):
        full = " ".join(SCHEMA_DDL)
        assert "profiles" in full
        assert "chat_sessions" in full
        assert "api_keys" in full
        assert "messages" in full
        # 4 tables + 3 indexes = 7 statements
        assert len(SCHEMA_DDL) == 9
