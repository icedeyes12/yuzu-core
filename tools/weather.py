import requests
import json


SCHEMA = {
    "type": "function",
    "function": {
        "name": "weather",
        "description": "Get current weather or daily forecast for a location using latitude and longitude.",
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {
                    "type": "number",
                    "description": "Latitude of the location"
                },
                "lon": {
                    "type": "number",
                    "description": "Longitude of the location"
                },
                "mode": {
                    "type": "string",
                    "enum": ["current", "forecast"],
                    "description": "Weather mode: 'current' for now, 'forecast' for 7-day daily forecast. Default: current"
                }
            },
            "required": ["lat", "lon"]
        }
    }
}

# WMO Weather interpretation codes
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def execute(arguments, **kwargs):
    from database import Database
    from tools.registry import build_markdown_contract

    lat = arguments.get("lat", 0)
    lon = arguments.get("lon", 0)
    mode = arguments.get("mode", "current")

    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    # Fall back to context-based location if not provided
    if lat == 0 and lon == 0:
        context = Database.get_context()
        location = context.get("location", {})
        lat = location.get("lat", 0)
        lon = location.get("lon", 0)

    if lat == 0 or lon == 0:
        return build_markdown_contract(
            "weather_tools",
            f"/weather {lat} {lon}",
            ["Error: location_not_set"],
            partner_name,
        )

    full_command = f"/weather {lat} {lon}" + (f" --mode={mode}" if mode != "current" else "")

    try:
        if mode == "forecast":
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
                    "timezone": "auto",
                    "forecast_days": 7
                },
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            lines = []
            for i, date in enumerate(dates):
                code = daily.get("weathercode", [0])[i] if i < len(daily.get("weathercode", [])) else 0
                weather_desc = WMO_CODES.get(code, f"Code {code}")
                temp_max = daily.get("temperature_2m_max", [None])[i] if i < len(daily.get("temperature_2m_max", [])) else None
                temp_min = daily.get("temperature_2m_min", [None])[i] if i < len(daily.get("temperature_2m_min", [])) else None
                precip = daily.get("precipitation_sum", [0])[i] if i < len(daily.get("precipitation_sum", [])) else 0
                wind = daily.get("windspeed_10m_max", [None])[i] if i < len(daily.get("windspeed_10m_max", [])) else None
                lines.append(f"{date}: {weather_desc}, {temp_min}–{temp_max}°C, Rain {precip}mm, Wind {wind} km/h")
            return build_markdown_contract("weather_tools", full_command, lines, partner_name)
        else:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": True
                },
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current_weather", {})
            weather_code = current.get("weathercode", 0)
            lines = [
                f"Temperature: {current.get('temperature')}°C",
                f"Weather: {WMO_CODES.get(weather_code, f'Code {weather_code}')}",
                f"Wind: {current.get('windspeed')} km/h",
            ]
            return build_markdown_contract("weather_tools", full_command, lines, partner_name)

    except Exception as e:
        return build_markdown_contract(
            "weather_tools", full_command,
            [f"Error: Weather fetch failed: {str(e)}"],
            partner_name,
        )
