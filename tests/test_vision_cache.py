"""Tests for vision context toggle behavior and base64 image caching."""

import sys
import os
import json
import base64
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import MultimodalTools
from database import Database, Message, get_db_session
from app import _cache_images_from_message, extract_recent_images, build_visual_context


class TestDownloadImageToCache(unittest.TestCase):
    """Tests for MultimodalTools.download_image_to_cache()."""

    def setUp(self):
        self.tools = MultimodalTools()
        # Use a temp directory as cache
        self.orig_cache = self.tools.IMAGE_CACHE_DIR
        self.tmp_dir = tempfile.mkdtemp()
        self.tools.IMAGE_CACHE_DIR = self.tmp_dir

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.tools.IMAGE_CACHE_DIR = self.orig_cache

    @patch('tools.requests.get')
    def test_downloads_and_saves_jpg(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.content = b'\xff\xd8\xff\xe0fake-jpg-bytes'
        response.headers = {'content-type': 'image/jpeg'}
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        result = self.tools.download_image_to_cache('https://example.com/photo.jpg')
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith('.jpg'))
        self.assertTrue(os.path.isfile(result))

    @patch('tools.requests.get')
    def test_downloads_and_saves_png(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.content = b'\x89PNG\r\n\x1a\nfake-png'
        response.headers = {'content-type': 'image/png'}
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        result = self.tools.download_image_to_cache('https://example.com/img.png')
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith('.png'))

    @patch('tools.requests.get')
    def test_returns_cached_file_on_second_call(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.content = b'image-bytes'
        response.headers = {'content-type': 'image/jpeg'}
        response.raise_for_status = MagicMock()
        mock_get.return_value = response

        url = 'https://example.com/cached.jpg'
        first = self.tools.download_image_to_cache(url)
        second = self.tools.download_image_to_cache(url)
        self.assertEqual(first, second)
        # Should only download once
        mock_get.assert_called_once()

    @patch('tools.requests.get')
    def test_returns_none_on_failure(self, mock_get):
        mock_get.side_effect = Exception('network error')
        result = self.tools.download_image_to_cache('https://example.com/broken.jpg')
        self.assertIsNone(result)


class TestEncodeImageToBase64(unittest.TestCase):
    """Tests for MultimodalTools.encode_image_to_base64()."""

    def test_encodes_existing_file(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'fake-png-data')
            path = f.name

        try:
            result = MultimodalTools.encode_image_to_base64(path)
            self.assertIsNotNone(result)
            self.assertEqual(result['type'], 'image_url')
            self.assertIn('data:image/png;base64,', result['image_url']['url'])
            # Verify base64 is correct
            b64_part = result['image_url']['url'].split(',', 1)[1]
            self.assertEqual(base64.b64decode(b64_part), b'fake-png-data')
        finally:
            os.unlink(path)

    def test_returns_none_for_missing_file(self):
        result = MultimodalTools.encode_image_to_base64('/nonexistent/file.png')
        self.assertIsNone(result)

    def test_jpg_mime_type(self):
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            f.write(b'fake-jpg')
            path = f.name
        try:
            result = MultimodalTools.encode_image_to_base64(path)
            self.assertIn('data:image/jpeg;base64,', result['image_url']['url'])
        finally:
            os.unlink(path)


class TestCacheImagesFromMessage(unittest.TestCase):
    """Tests for _cache_images_from_message()."""

    @patch('app.multimodal_tools')
    def test_caches_markdown_image(self, mock_tools):
        mock_tools.download_image_to_cache.return_value = '/cache/abc.png'
        mock_tools.extract_image_urls.return_value = []

        result = _cache_images_from_message('Check this ![img](https://example.com/pic.png)')
        self.assertEqual(result, ['/cache/abc.png'])
        mock_tools.download_image_to_cache.assert_called_once_with('https://example.com/pic.png')

    @patch('app.multimodal_tools')
    def test_caches_bare_url(self, mock_tools):
        mock_tools.download_image_to_cache.return_value = '/cache/xyz.jpg'
        mock_tools.extract_image_urls.return_value = ['https://example.com/pic.jpg']

        result = _cache_images_from_message('Look at https://example.com/pic.jpg')
        self.assertEqual(result, ['/cache/xyz.jpg'])

    def test_handles_uploaded_images(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'uploaded')
            path = f.name
        try:
            msg = f"UPLOADED_IMAGES:\nIMAGE_UPLOAD:{path}\nUSER_MESSAGE:check this"
            result = _cache_images_from_message(msg)
            self.assertEqual(result, [path])
        finally:
            os.unlink(path)

    @patch('app.multimodal_tools')
    def test_returns_empty_for_text_only(self, mock_tools):
        mock_tools.extract_image_urls.return_value = []
        result = _cache_images_from_message('Hello there')
        self.assertEqual(result, [])


class TestDatabaseImagePaths(unittest.TestCase):
    """Tests for image_paths column in database."""

    def test_add_message_with_image_paths(self):
        paths = ['/cache/abc.png', '/cache/def.jpg']
        sid = Database.create_session("test_img_paths")
        Database.add_message('user', 'test image', session_id=sid, image_paths=paths)
        history = Database.get_chat_history(session_id=sid, limit=1, recent=True)
        last = history[-1]
        self.assertEqual(last['image_paths'], paths)

    def test_add_message_without_image_paths(self):
        # Create a fresh session to avoid interference
        sid = Database.create_session("test_no_img")
        Database.add_message('user', 'text only', session_id=sid)
        history = Database.get_chat_history(session_id=sid, limit=1, recent=True)
        last = history[-1]
        self.assertEqual(last['image_paths'], [])


class TestImageCacheDirectory(unittest.TestCase):
    """Tests for cache directory creation."""

    def test_cache_dir_created_on_init(self):
        tools = MultimodalTools()
        self.assertTrue(os.path.isdir(tools.IMAGE_CACHE_DIR))


if __name__ == '__main__':
    unittest.main()
