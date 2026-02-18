import json
import os
import requests
from datetime import datetime
from database import Database

HUNYUAN_ENDPOINT = "https://chutes-hunyuan-image-3.chutes.ai/generate"
Z_TURBO_ENDPOINT = "https://chutes-z-image-turbo.chutes.ai/generate"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "image_generate",
        "description": "Generate an image from a text prompt. Only use when image generation protocol is activated.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The image generation prompt describing what to create"
                }
            },
            "required": ["prompt"]
        }
    }
}


def execute(arguments, **kwargs):
    prompt = arguments.get("prompt", "")
    if not prompt:
        return json.dumps({"error": "No prompt provided"})

    try:
        api_keys = Database.get_api_keys()
        api_key = api_keys.get('chutes')
        if not api_key:
            return json.dumps({"error": "No Chutes API key available"})

        # Resolve image model from profile
        profile = Database.get_profile()
        image_model = (profile or {}).get("image_model", "hunyuan")

        if image_model == "z_turbo":
            endpoint = Z_TURBO_ENDPOINT
        else:
            endpoint = HUNYUAN_ENDPOINT

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {"prompt": prompt}

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

            print(f"[Image] {filepath} (model={image_model})")

            return json.dumps({
                "image_path": filepath,
                "image_markdown": f"![Generated Image]({filepath})"
            })
        else:
            return json.dumps({"error": f"API error {response.status_code}"})

    except Exception as e:
        return json.dumps({"error": f"Image generation failed: {str(e)}"})
