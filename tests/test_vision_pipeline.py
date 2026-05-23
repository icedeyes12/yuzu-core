from __future__ import annotations

import os
from unittest.mock import patch
import sys

# Ensure app is in path
sys.path.append('/home/workspace/yuzu-companion')

from app.tools.multimodal import MultimodalTools

def test_inject_vision_context_no_vision_model():
    tools = MultimodalTools()
    messages = [{"role": "user", "content": "hello", "image_paths": ["path1.jpg"]}]
    with patch.object(MultimodalTools, 'is_vision_model', return_value=False):
        result = tools.inject_vision_context(messages, "non-vision-model")
        assert result == messages

def test_inject_vision_context_with_vision_model():
    tools = MultimodalTools()
    messages = [{"role": "user", "content": "what is this?", "image_paths": ["tests/assets/test.jpg"]}]
    
    os.makedirs("tests/assets", exist_ok=True)
    from PIL import Image
    img = Image.new('RGB', (100, 100), color = 'red')
    img.save("tests/assets/test.jpg")
    
    with patch.object(MultimodalTools, 'is_vision_model', return_value=True):
        result = tools.inject_vision_context(messages, "vision-model")
        assert len(result) == 1
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["type"] == "text"
        assert result[0]["content"][1]["type"] == "image_url"
        assert "image_paths" not in result[0]

def test_vision_model_validation_llm_client():
    from app.llm_client import generate_ai_response
    
    profile = {"providers_config": {"preferred_provider": "ollama", "preferred_model": "non-vision"}}
    user_message = "![test](static/uploads/test.jpg)"
    
    with patch('app.tools.multimodal.multimodal_tools.has_images', return_value=True), \
         patch('app.tools.multimodal.multimodal_tools.is_vision_model', return_value=False), \
         patch('app.db.Database.get_active_session', return_value={"id": 1}), \
         patch('app.db.Database.add_message') as mock_add:
        
        text, raw = generate_ai_response(profile, user_message, session_id=1)
        
        assert "[System] Current model does not support vision" in text
        assert raw is None
        mock_add.assert_called_with("system", text, session_id=1)
