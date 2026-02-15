"""Tests for recent image context extraction logic."""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import MultimodalTools


class TestExtractRecentImageContents(unittest.TestCase):
    """Tests for MultimodalTools.extract_recent_image_contents()."""

    def setUp(self):
        self.tools = MultimodalTools()

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_extracts_images_from_recent_messages(self, mock_download):
        mock_download.return_value = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        history = [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "look at this ![photo](http://example.com/img.png)"},
            {"role": "assistant", "content": "nice image!"},
        ]
        result = self.tools.extract_recent_image_contents(history)
        self.assertEqual(len(result), 1)
        mock_download.assert_called_once_with("http://example.com/img.png")

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_max_3_images(self, mock_download):
        mock_download.return_value = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        history = [
            {"role": "user", "content": "![a](http://example.com/1.png)"},
            {"role": "user", "content": "![b](http://example.com/2.png)"},
            {"role": "user", "content": "![c](http://example.com/3.png)"},
            {"role": "user", "content": "![d](http://example.com/4.png)"},
        ]
        result = self.tools.extract_recent_image_contents(history)
        self.assertEqual(len(result), 3)

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_most_recent_first(self, mock_download):
        """Most recent images are collected first, then returned in chronological order."""
        def side_effect(url):
            return {"type": "image_url", "image_url": {"url": f"encoded:{url}"}}
        mock_download.side_effect = side_effect

        history = [
            {"role": "user", "content": "![a](http://example.com/old.png)"},
            {"role": "user", "content": "![b](http://example.com/mid.png)"},
            {"role": "user", "content": "![c](http://example.com/new.png)"},
            {"role": "user", "content": "![d](http://example.com/newest.png)"},
        ]
        result = self.tools.extract_recent_image_contents(history, max_images=2)
        # Should pick the 2 most recent, returned in chronological order
        self.assertEqual(len(result), 2)
        self.assertIn("new.png", result[0]["image_url"]["url"])
        self.assertIn("newest.png", result[1]["image_url"]["url"])

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_no_images_returns_empty(self, mock_download):
        history = [
            {"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "hi!"},
        ]
        result = self.tools.extract_recent_image_contents(history)
        self.assertEqual(result, [])
        mock_download.assert_not_called()

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_lookback_limits_scan(self, mock_download):
        mock_download.return_value = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        history = (
            [{"role": "user", "content": "![old](http://example.com/old.png)"}]
            + [{"role": "user", "content": "text only"} for _ in range(20)]
        )
        result = self.tools.extract_recent_image_contents(history, lookback=5)
        self.assertEqual(result, [])

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_skips_failed_downloads(self, mock_download):
        mock_download.return_value = None
        history = [
            {"role": "user", "content": "![a](http://example.com/broken.png)"},
        ]
        result = self.tools.extract_recent_image_contents(history)
        self.assertEqual(result, [])

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_non_string_content_skipped(self, mock_download):
        history = [
            {"role": "user", "content": [{"type": "text", "text": "already formatted"}]},
            {"role": "user", "content": "![a](http://example.com/img.png)"},
        ]
        mock_download.return_value = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        result = self.tools.extract_recent_image_contents(history)
        self.assertEqual(len(result), 1)

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_multiple_images_in_single_message(self, mock_download):
        mock_download.return_value = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        history = [
            {"role": "user", "content": "![a](http://example.com/1.png) ![b](http://example.com/2.png) ![c](http://example.com/3.png) ![d](http://example.com/4.png)"},
        ]
        result = self.tools.extract_recent_image_contents(history, max_images=3)
        self.assertEqual(len(result), 3)

    @patch.object(MultimodalTools, 'download_and_encode_image')
    def test_empty_history(self, mock_download):
        result = self.tools.extract_recent_image_contents([])
        self.assertEqual(result, [])
        mock_download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
