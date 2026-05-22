# FILE: tests/test_prompts.py
# DESCRIPTION: Pure-function tests for app.prompts.

from __future__ import annotations

from app.prompts import closeness_mode


class TestClosenessMode:
    def test_distant_band(self):
        assert closeness_mode(0) == "distant but attentive"
        assert closeness_mode(24) == "distant but attentive"

    def test_reserved_band(self):
        assert closeness_mode(25) == "reserved and observant"
        assert closeness_mode(44) == "reserved and observant"

    def test_comfortable_band(self):
        assert closeness_mode(45) == "comfortable and open"
        assert closeness_mode(64) == "comfortable and open"

    def test_close_band(self):
        assert closeness_mode(65) == "close and warm"
        assert closeness_mode(84) == "close and warm"

    def test_intimate_band(self):
        assert closeness_mode(85) == "deeply attuned and intimate"
        assert closeness_mode(100) == "deeply attuned and intimate"
        assert closeness_mode(150) == "deeply attuned and intimate"
