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
    from tools.registry import build_markdown_contract

    prompt = arguments.get("prompt", "")
    if not prompt:
        return build_markdown_contract(
            "image_tools", "/imagine", ["Error: No prompt provided"], "Yuzu"
        )

    try:
        api_keys = Database.get_api_keys()
        api_key = api_keys.get('chutes')
        if not api_key:
            profile = Database.get_profile() or {}
            partner_name = profile.get("partner_name", "Yuzu")
            return build_markdown_contract(
                "image_tools", f"/imagine {prompt}",
                ["Error: No Chutes API key available"],
                partner_name,
            )

        # Resolve image model from profile — no silent fallback
        profile = Database.get_profile() or {}
        partner_name = profile.get("partner_name", "Yuzu")
        image_model = profile.get("image_model", "hunyuan")
        
        print(f"[IMAGE TOOL] Model: {image_model}")

        if image_model == "z_turbo":
            endpoint = Z_TURBO_ENDPOINT
        else:
            endpoint = HUNYUAN_ENDPOINT
        
        print(f"[IMAGE TOOL] Endpoint: {endpoint}")

        # Runtime model logging (mandatory per spec)
        print(f"[IMAGE TOOL]")
        print(f"Selected model: {image_model}")
        print(f"Endpoint: {endpoint}")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {"prompt": prompt}
        
        print(f"[IMAGE TOOL] Generating image (prompt length: {len(prompt)} chars)")

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

            print(f"[IMAGE TOOL] Saved: {filepath}")

            full_command = f"/imagine {prompt}"
            return build_markdown_contract(
                "image_tools", full_command,
                [f'<img src="static/generated_images/{filename}" alt="Generated Image">'],
                partner_name,
            )
        else:
            print(f"[IMAGE TOOL] API error {response.status_code}")
            return build_markdown_contract(
                "image_tools", f"/imagine {prompt}",
                [f"Error: API error {response.status_code}"],
                partner_name,
            )

    except Exception as e:
        print(f"[IMAGE TOOL] Exception: {str(e)}")
        profile = Database.get_profile() or {}
        partner_name = profile.get("partner_name", "Yuzu")
        return build_markdown_contract(
            "image_tools", f"/imagine {prompt}",
            [f"Error: Image generation failed: {str(e)}"],
            partner_name,
        )
