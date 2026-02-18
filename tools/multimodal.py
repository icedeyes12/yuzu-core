# [FILE: tools.py]
# [VERSION: 1.0.0.69.4v2]
# [DATE: 2025-08-12]
# [PROJECT: HKKM - Yuzu Companion]
# [DESCRIPTION: Multimodal tools with image caching]
# [AUTHOR: Project Lead: Bani Baskara]
# [TEAM: Deepseek, GPT, Qwen, Gemini]
# [REPOSITORY: https://guthib.com/icedeyes12]
# [LICENSE: MIT]

import requests
import json
import base64
import re
import time
import os
import hashlib
import shutil
import subprocess
from urllib.parse import unquote
from datetime import datetime
from database import Database
from typing import List, Dict, Optional, Tuple

class MultimodalTools:
    IMAGE_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'image_cache')

    def __init__(self):
        # ONLY moonshotai/kimi-k2.5 for vision (OpenRouter only)
        self.vision_models = {
            'openrouter': [
                "moonshotai/kimi-k2.5"  # Only this model for vision
            ]
        }
        
        self.provider_endpoints = {
            'chutes': "https://llm.chutes.ai/v1/chat/completions",
            'openrouter': "https://openrouter.ai/api/v1/chat/completions",
            'chutes_image': "https://image.chutes.ai/generate"
        }
        
        # Image generation models
        self.image_generation_models = {
            'chutes': [
                ("hunyuan-image-3", "https://chutes-hunyuan-image-3.chutes.ai/generate"),
            ]
        }
        
        # Image cache for base64 encoded images
        self.image_cache = {}
        self.cache_ttl = 3600  # 1 hour TTL
        
        # Ensure cache directory exists
        os.makedirs(self.IMAGE_CACHE_DIR, exist_ok=True)
        
    def get_available_vision_models(self, provider: str) -> List[str]:
        return self.vision_models.get(provider, [])
    
    def get_provider_endpoint(self, provider: str) -> Optional[str]:
        return self.provider_endpoints.get(provider)
    
    def is_vision_model(self, model_name: str, provider: str = None) -> bool:
        if provider:
            return any(vision_model.lower() in model_name.lower() 
                      for vision_model in self.vision_models.get(provider, []))
        else:
            for provider_models in self.vision_models.values():
                if any(vision_model.lower() in model_name.lower() 
                      for vision_model in provider_models):
                    return True
        return False

    def _clean_cache(self):
        """Remove expired cache entries"""
        current_time = time.time()
        expired_keys = [
            key for key, (timestamp, _) in self.image_cache.items()
            if current_time - timestamp > self.cache_ttl
        ]
        for key in expired_keys:
            del self.image_cache[key]

    def download_image_to_cache(self, url: str) -> Optional[str]:
        """Download an image from *url*, save it under ``IMAGE_CACHE_DIR`` and
        return the local file path.  The filename is derived from a SHA-1 hash
        of the URL so repeated downloads are avoided."""
        # Validate URL scheme to prevent SSRF attacks
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return None
        # Block requests to localhost / private IPs
        hostname = parsed.hostname or ''
        if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1', ''):
            return None

        url_hash = hashlib.sha1(url.encode('utf-8')).hexdigest()  # nosec - not used for security

        # Check if already cached with any common extension
        for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
            candidate = os.path.join(self.IMAGE_CACHE_DIR, f"{url_hash}{ext}")
            if os.path.isfile(candidate):
                print(f"[Vision] Using cached image → {candidate}")
                return candidate

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '')
            if 'png' in content_type:
                ext = '.png'
            elif 'gif' in content_type:
                ext = '.gif'
            elif 'webp' in content_type:
                ext = '.webp'
            else:
                ext = '.jpg'

            filepath = os.path.join(self.IMAGE_CACHE_DIR, f"{url_hash}{ext}")
            with open(filepath, 'wb') as f:
                f.write(response.content)

            print(f"[Vision] Downloaded image → {filepath}")
            return filepath
        except Exception as e:
            print(f"[WARNING] Failed to download image from {url}: {e}")
            return None

    @staticmethod
    def encode_image_to_base64(filepath: str) -> Optional[Dict]:
        """Read a local image file and return an OpenAI-compatible
        ``image_url`` content block with a ``data:`` URI."""
        if not os.path.isfile(filepath):
            return None

        lower = filepath.lower()
        if lower.endswith('.png'):
            mime = 'image/png'
        elif lower.endswith('.gif'):
            mime = 'image/gif'
        elif lower.endswith('.webp'):
            mime = 'image/webp'
        else:
            mime = 'image/jpeg'

        with open(filepath, 'rb') as f:
            data = base64.b64encode(f.read()).decode('utf-8')

        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{data}"}
        }

    def extract_image_urls(self, text: str) -> List[str]:
        url_pattern = r'https?://[^\s<>"\'{}]+'
        urls = re.findall(url_pattern, text, re.IGNORECASE)
        
        image_urls = []
        for url in urls:
            if self._is_url_in_code_context(text, url):
                continue
                
            if any(domain in url.lower() for domain in [
                'ibb.co', 'imgur.com', 'gyazo.com', 'prntscr.com', 'prnt.sc',
                'tinypic.com', 'postimg.org', 'imageshack.us', 'flickr.com',
                'deviantart.com', 'artstation.com', 'pinterest.com',
                'cdn.discordapp.com', 'media.discordapp.net', 'i.redd.it',
                'i.imgur.com'
            ]):
                image_urls.append(url)
            elif re.search(r'\.(jpg|jpeg|png|gif|webp|bmp|svg)(\?.*)?$', url.lower()):
                image_urls.append(url)
            elif re.search(r'/[a-z0-9]{7,}', url.lower()):
                image_urls.append(url)
        
        return image_urls

    def _is_url_in_code_context(self, text: str, url: str) -> bool:
        url_pos = text.find(url)
        if url_pos == -1:
            return False
        
        before_context = text[max(0, url_pos-20):url_pos]
        after_context = text[url_pos+len(url):min(len(text), url_pos+len(url)+20)]
        
        code_indicators = [
            'import ', 'from ', 'def ', 'class ', '//', '#', 
            '"""', "'''", '/*', '*/', '`', '```'
        ]
        
        for indicator in code_indicators:
            if indicator in before_context or indicator in after_context:
                return True
        
        quote_count_before = before_context.count('"') + before_context.count("'")
        quote_count_after = after_context.count('"') + after_context.count("'")
        
        if (quote_count_before + quote_count_after) % 2 == 1:
            return True
        
        return False

    def _looks_like_code(self, text: str) -> bool:
        code_indicators = [
            'import ', 'from ', 'def ', 'class ', 'if __name__',
            '```', '    ', '\t', '// ', '# ', '/*', '*/'
        ]
        return any(indicator in text for indicator in code_indicators)

    def _is_likely_actual_image(self, url: str) -> bool:
        excluded_patterns = [
            'api/v1/chat/completions',
            'v1/chat/completions', 
            'github.com',
            'openrouter.ai/api',
            'llm.chutes.ai/v1'
        ]
        
        if any(pattern in url.lower() for pattern in excluded_patterns):
            return False
        
        image_domains = ['ibb.co', 'imgur.com', 'i.imgur.com', 'cdn.discordapp.com']
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
        
        return (any(domain in url.lower() for domain in image_domains) or
                any(ext in url.lower() for ext in image_extensions))

    def has_images(self, text: str) -> bool:
        if "![" in text and "](" in text and ")" in text:
            image_sources = self._extract_image_sources_from_markdown(text)
            if image_sources:
                return True
        
        if "UPLOADED_IMAGES:" in text and "IMAGE_UPLOAD:" in text:
            return True
        
        upload_patterns = [
            'UPLOADED_IMAGES:',
            'IMAGE_UPLOAD:',
            'static/uploads/',
            'static/generated_images/',
        ]
        
        if any(pattern in text for pattern in upload_patterns):
            return True
        
        urls = self.extract_image_urls(text)
        
        if self._looks_like_code(text):
            return len(urls) > 0 and any(self._is_likely_actual_image(url) for url in urls)
        
        return len(urls) > 0
    
    def download_and_encode_image(self, image_url: str) -> Optional[Dict]:
        """Download and encode image with caching support"""
        # Clean expired cache entries
        self._clean_cache()
        
        # Check cache first
        if image_url in self.image_cache:
            timestamp, cached_data = self.image_cache[image_url]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data
        
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '')
            if 'jpeg' in content_type or 'jpg' in content_type:
                mime_type = "image/jpeg"
            elif 'png' in content_type:
                mime_type = "image/png"
            elif 'gif' in content_type:
                mime_type = "image/gif"
            elif 'webp' in content_type:
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"
            
            image_data = base64.b64encode(response.content).decode('utf-8')
            result = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{image_data}"
                }
            }
            
            # Cache the result
            self.image_cache[image_url] = (time.time(), result)
            return result
            
        except Exception as e:
            return None
    
    def format_vision_message(self, user_message: str, provider: str = None) -> List[Dict]:
        image_sources = self._extract_image_sources_from_markdown(user_message)
        
        if not image_sources:
            return [{"role": "user", "content": user_message}]
        
        clean_text = self._remove_image_markdown(user_message)
        
        content = [{"type": "text", "text": clean_text or "What's in this image?"}]
        
        for source in image_sources[:3]:  # Limit to 3 images
            if source.startswith(('http://', 'https://')):
                # Remote URL — download to cache, then encode
                cached_path = self.download_image_to_cache(source)
                if cached_path:
                    image_content = self.encode_image_to_base64(cached_path)
                    if image_content:
                        content.append(image_content)
            else:
                # Local file path — encode directly
                image_content = self.encode_image_to_base64(source)
                if image_content:
                    print(f"[Vision] Encoded local image → {source}")
                    content.append(image_content)
        
        return [{"role": "user", "content": content}]

    def _extract_image_sources_from_markdown(self, text: str) -> List[str]:
        """Extract image sources from markdown.  Returns local file paths for
        on-disk images and URLs for remote images."""
        import re
        
        markdown_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        matches = re.findall(markdown_pattern, text)
        
        image_sources = []
        for alt, url in matches:
            if 'onerror=' in url or 'onload=' in url or 'uploaded-image-container' in url:
                continue
                
            if url.startswith('static/uploads/') or url.startswith('static/generated_images/'):
                # Local file — return path directly (don't convert to localhost URL)
                image_sources.append(url)
            elif url.startswith('uploads/') or url.startswith('generated_images/'):
                image_sources.append(f"static/{url}")
            else:
                image_sources.append(url)
        
        return image_sources

    def _remove_image_markdown(self, text: str) -> str:
        import re
        
        def replace_markdown(match):
            alt_text = match.group(1)
            if alt_text and alt_text not in ['Uploaded Image', 'Generated Image']:
                return f" [Image: {alt_text}] "
            return " [Image] "
        
        clean_text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_markdown, text)
        
        clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
        clean_text = clean_text.strip()
        
        return clean_text

    def _format_uploaded_images_vision(self, user_message: str, provider: str = None) -> List[Dict]:
        import base64
        
        parts = user_message.split("UPLOADED_IMAGES:")
        if len(parts) < 2:
            return [{"role": "user", "content": user_message}]
            
        images_part = parts[1]
        
        user_text = ""
        image_paths = []
        
        for line in images_part.split('\n'):
            if line.startswith("USER_MESSAGE:"):
                user_text = line.replace("USER_MESSAGE:", "").strip()
            elif line.startswith("IMAGE_UPLOAD:"):
                path = line.replace("IMAGE_UPLOAD:", "").strip()
                image_paths.append(path)
        
        content = [{"type": "text", "text": user_text or "Analyze these images"}]
        
        for i, image_path in enumerate(image_paths[:3]):
            try:
                with open(image_path, 'rb') as f:
                    image_bytes = f.read()
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                
                if image_path.lower().endswith('.png'):
                    mime_type = "image/png"
                elif image_path.lower().endswith('.jpg') or image_path.lower().endswith('.jpeg'):
                    mime_type = "image/jpeg"
                elif image_path.lower().endswith('.gif'):
                    mime_type = "image/gif"
                else:
                    mime_type = "image/jpeg"
                
                data_url = f"data:{mime_type};base64,{image_base64}"
                
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                })
                
            except Exception as e:
                pass
        
        return [{"role": "user", "content": content}]
    
    def detect_image_generation_request(self, text: str, is_ai_response: bool = False) -> bool:
        text_lower = text.lower().strip()
        
        if is_ai_response:
            return text_lower.startswith('/imagine') or text_lower.startswith('imagine ')
        else:
            if '/imagine' in text_lower:
                return True
            
            image_keywords = ['generate an image', 'create an image', 'make a picture', 
                            'draw me', 'show me an image', 'generate image', 'create image']
            return any(keyword in text_lower for keyword in image_keywords)
    
    def extract_imagine_prompt(self, text: str, is_ai_response: bool = False) -> str:
        text_lower = text.lower()
        
        if is_ai_response:
            if text_lower.startswith('/imagine'):
                prompt = text[8:].strip()
            elif text_lower.startswith('imagine '):
                prompt = text[8:].strip()
            else:
                prompt = text.strip()
        else:
            if '/imagine' in text_lower:
                parts = text_lower.split('/imagine', 1)
                prompt = parts[1].strip() if len(parts) > 1 else text.strip()
            else:
                prompt = text.strip()
                remove_phrases = [
                    'can you', 'please', 'could you', 'would you', 
                    'generate an image of', 'create an image of', 
                    'make a picture of', 'draw me', 'show me an image of'
                ]
                for phrase in remove_phrases:
                    if prompt.lower().startswith(phrase):
                        prompt = prompt[len(phrase):].strip()
                        break
        
        prompt = prompt.replace('"', '').replace("'", "").strip()
        
        if prompt.endswith('.') and not prompt.endswith('...'):
            prompt = prompt[:-1]
            
        return prompt
    
    def generate_image(self, prompt: str, provider: str = "chutes", 
                      model: str = None, size: str = "1024x1024") -> Tuple[Optional[str], Optional[str]]:
        """
        Legacy image generation function.
        
        NOTE: Tool-based image generation is now centralized in tools/image_generate.py
        This function is kept for backward compatibility with direct /imagine commands.
        """
        try:
            api_keys = Database.get_api_keys()
            
            if provider == "chutes":
                api_key = api_keys.get('chutes')
                if not api_key:
                    return None, "No Chutes API key available"
                
                if not model:
                    model = self.image_generation_models['chutes'][0]
                
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                width, height = map(int, size.split('x'))
                
                if isinstance(model, tuple):
                    model_name, endpoint = model
                else:
                    model_name = model
                    endpoint = self.provider_endpoints['chutes_image']
                
                if "hunyuan-image-3" in endpoint:
                    payload = {
                        "prompt": prompt
                    }
                elif "hidream" in endpoint:
                    payload = {
                        "seed": None,
                        "prompt": prompt,
                        "resolution": f"{width}x{height}",
                        "guidance_scale": 7.5,
                        "num_inference_steps": 30
                    }
                else:
                    payload = {
                        "model": model_name,
                        "prompt": prompt,
                        "negative_prompt": "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, child, loli, kid, teenager, big chest, big boobs, huge boobs, fat, weird proportions, bad head, bad body, low quality",
                        "guidance_scale": 7.5,
                        "width": width,
                        "height": height,
                        "num_inference_steps": 30
                    }
                
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 200:
                    images_dir = "static/generated_images"
                    os.makedirs(images_dir, exist_ok=True)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_prompt = "".join(c for c in prompt[:30] if c.isalnum() or c in (' ', '-', '_')).rstrip()
                    filename = f"{timestamp}_{safe_prompt}.png"
                    filepath = os.path.join(images_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    
                    print(f"[Image] {filepath}")
                    preview_image_in_terminal(filepath)
                    
                    return filepath, None
                else:
                    return None, f"API error {response.status_code}"
            
            else:
                return None, f"Image generation not supported for provider: {provider}"
                
        except Exception as e:
            return None, f"Image generation failed: {str(e)}"
    
    def get_best_vision_provider(self) -> Tuple[Optional[str], Optional[str]]:
        api_keys = Database.get_api_keys()
        
        # ONLY check for openrouter with kimi-k2.5
        if 'openrouter' in api_keys:
            openrouter_models = self.get_available_vision_models('openrouter')
            if openrouter_models:
                return 'openrouter', openrouter_models[0]  # Will be "moonshotai/kimi-k2.5"
        
        # No vision from chutes anymore - ONLY OpenRouter
        return None, None
    
    def should_use_vision(self, user_message: str, current_provider: str, current_model: str) -> bool:
        if not self.has_images(user_message):
            return False
        
        if ('onerror=' in user_message or 'onload=' in user_message or 
            'uploaded-image-container' in user_message or 'generated-image-container' in user_message):
            return False
        
        if self._looks_like_code(user_message):
            return False
        
        # Check if current model is already the vision model
        if current_model == "moonshotai/kimi-k2.5" and current_provider == "openrouter":
            return True
        
        # Check if we can switch to vision
        vision_provider, vision_model = self.get_best_vision_provider()
        return vision_provider is not None

    def detect_uploaded_images(self, text: str) -> List[str]:
        upload_patterns = [
            r'static/uploads/\d{8}_\d{6}_\d+_[^\s\)]+',
            r'static/generated_images/\d{8}_\d{6}_[^\s\)]+',
            r'!\[Image \d+\]\([^)]+\)'
        ]
        
        found_images = []
        for pattern in upload_patterns:
            matches = re.findall(pattern, text)
            found_images.extend(matches)
        
        return found_images


def preview_image_in_terminal(image_path):
    """Preview an image in the terminal using timg."""
    if not shutil.which("timg"):
        return
    image_path = unquote(image_path)
    image_path = os.path.abspath(image_path)
    if not os.path.isfile(image_path):
        print(f"[DEBUG] preview_image_in_terminal: file not found: {image_path}")
        return
    subprocess.run(["timg", "-g", "80x40", image_path])


multimodal_tools = MultimodalTools()