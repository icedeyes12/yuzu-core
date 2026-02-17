import requests
import json


SCHEMA = {
    "type": "function",
    "function": {
        "name": "weather",
        "description": "Get current weather for a location using latitude and longitude.",
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
    lat = arguments.get("lat", 0)
    lon = arguments.get("lon", 0)

    if lat == 0 and lon == 0:
        return json.dumps({"error": "location_not_set"})

    try:
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

        return json.dumps({
            "temperature": current.get("temperature"),
            "weather": WMO_CODES.get(weather_code, f"Code {weather_code}"),
            "wind_speed": current.get("windspeed")
        })

    except Exception as e:
        return json.dumps({"error": f"Weather fetch failed: {str(e)}"})
