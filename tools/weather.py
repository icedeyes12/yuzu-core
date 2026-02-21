import requests
import json


SCHEMA = {
    "type": "function",
    "function": {
        "name": "weather",
        "description": "Call any Open-Meteo endpoint with arbitrary parameters.",
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": "API path like /v1/forecast, /v1/air-quality, /v1/marine, /v1/archive"
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters for the endpoint"
                }
            },
            "required": ["endpoint", "params"]
        }
    }
}

def execute(arguments, **kwargs):
    from database import Database
    from tools.registry import build_markdown_contract
    import requests
    import json

    endpoint = arguments.get("endpoint", "").strip()
    params = arguments.get("params", {})

    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    # --- Guard endpoint ---
    if not endpoint.startswith("/v1/"):
        return build_markdown_contract(
            "weather_tools",
            f"/weather {endpoint}",
            ["Error: invalid_endpoint"],
            partner_name,
        )

    base_url = "https://api.open-meteo.com"

    # --- Inject fallback location ---
    context = Database.get_context()
    location = context.get("location", {})
    lat = location.get("lat")
    lon = location.get("lon")

    if lat and "latitude" not in params:
        params["latitude"] = lat
    if lon and "longitude" not in params:
        params["longitude"] = lon

    # --- Inject timezone fallback ---
    if "timezone" not in params:
        params["timezone"] = "auto"

    full_command = f"/weather {endpoint} {json.dumps(params)}"

    try:
        resp = requests.get(
            f"{base_url}{endpoint}",
            params=params,
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        raw_json = json.dumps(data, indent=2)

        return build_markdown_contract(
            "weather_tools",
            full_command,
            raw_json.splitlines(),
            partner_name
        )

    except Exception as e:
        return build_markdown_contract(
            "weather_tools",
            full_command,
            [f"Error: {str(e)}"],
            partner_name
        )