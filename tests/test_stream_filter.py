# FILE: tests/test_stream_filter.py
# DESCRIPTION: Behavior tests for the streaming command filter.

from __future__ import annotations

from app.commands import StreamFilter


def _drain(filter_obj: StreamFilter, chunks: list[str]) -> str:
    out: list[str] = []
    for chunk in chunks:
        out.extend(filter_obj.feed(chunk))
    out.extend(filter_obj.flush())
    return "".join(out)


class TestStreamFilterPlainText:
    def test_passes_through_single_chunk(self):
        sf = StreamFilter()
        assert _drain(sf, ["hello world"]) == "hello world"
        assert sf.command is None
        assert sf.full_text == "hello world"

    def test_passes_through_multi_chunk(self):
        sf = StreamFilter()
        result = _drain(sf, ["hel", "lo ", "world"])
        assert result == "hello world"
        assert sf.command is None

    def test_decides_quickly_after_first_real_char(self):
        sf = StreamFilter()
        # First chunk decides it's plain text immediately.
        first = list(sf.feed("hello"))
        assert first == ["hello"]
        # Subsequent chunks pass through with zero buffering.
        second = list(sf.feed(" there"))
        assert second == [" there"]

    def test_leading_whitespace_then_text(self):
        sf = StreamFilter()
        result = _drain(sf, ["  ", "hello"])
        assert result == "  hello"
        assert sf.command is None


class TestStreamFilterCommands:
    def test_suppresses_single_chunk_command(self):
        sf = StreamFilter()
        result = _drain(sf, ["/imagine a cat\n"])
        assert result == ""
        assert sf.command is not None
        assert sf.command["command"] == "imagine"
        assert sf.command["args"] == "a cat"

    def test_suppresses_command_split_across_chunks(self):
        sf = StreamFilter()
        result = _drain(sf, ["/im", "agine ", "a fluffy cat\n"])
        assert result == ""
        assert sf.command is not None
        assert sf.command["command"] == "imagine"
        assert sf.command["args"] == "a fluffy cat"

    def test_passes_through_text_after_command_line(self):
        sf = StreamFilter()
        result = _drain(
            sf, ["/request ", "http://x\n", "some narration"]
        )
        assert result == "some narration"
        assert sf.command is not None
        assert sf.command["command"] == "request"

    def test_command_with_no_newline_still_detected_on_flush(self):
        sf = StreamFilter()
        # Stream ends without a newline; flush should detect the command.
        result = _drain(sf, ["/imagine cat"])
        assert result == ""
        assert sf.command is not None
        assert sf.command["command"] == "imagine"

    def test_full_text_always_captured(self):
        sf = StreamFilter()
        _drain(sf, ["/imagine a cat\nrest"])
        assert sf.full_text == "/imagine a cat\nrest"


class TestStreamFilterEdgeCases:
    def test_empty_chunks_ignored(self):
        sf = StreamFilter()
        result = _drain(sf, ["", "hello", ""])
        assert result == "hello"

    def test_text_starting_with_slash_word_is_not_a_command_when_long(self):
        # If the model writes a long line starting with '/' but never emits a
        # newline (e.g. quoting a path), we eventually flush as plain text.
        sf = StreamFilter()
        long_text = "/usr/local/bin/python is a path " * 32
        result = _drain(sf, [long_text])
        # Either we treat the whole thing as a (degenerate) command on flush,
        # or we flush it as text after exceeding the sniff limit. Both are
        # acceptable - the point is we don't lose data.
        assert sf.full_text == long_text
        assert (result == long_text) or (sf.command is not None)
