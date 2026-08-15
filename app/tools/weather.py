from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.db import Database
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)
_REVERSE_GEOCODING_URL = "https://nominatim.openstreetmap.org/reverse"


class WeatherRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    location: str | None = Field(default=None, description="City or place name")
    date: str | None = Field(
        default=None,
        description="today, tomorrow, day_after_tomorrow, or YYYY-MM-DD",
    )
    days: int = Field(default=1, ge=1, le=7, description="Forecast length in days")


TOOL_NAME = "weather"
TOOL_WEATHER = ToolDefinition(
    name=TOOL_NAME,
    description=(
        "Get current weather and a forecast for up to 7 days. "
        "Use location for a city/place instead of the user's configured location. "
        "Use date for today, tomorrow, day_after_tomorrow, or YYYY-MM-DD."
    ),
    role="info_tools",
    parameters=[
        ToolParam(
            name="location",
            description="Optional city or place name, for example Melbourne",
            type="string",
            required=False,
        ),
        ToolParam(
            name="date",
            description="Optional today, tomorrow, day_after_tomorrow, or YYYY-MM-DD",
            type="string",
            required=False,
        ),
        ToolParam(
            name="days",
            description="Optional forecast length from 1 to 7 days",
            type="integer",
            required=False,
            default=1,
        ),
    ],
    needs_session=True,
)

TOOL_DEFINITION = {TOOL_NAME: TOOL_WEATHER}

_WMO_CONDITIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_")
    today = date.today()
    if normalized == "today":
        return today
    if normalized == "tomorrow":
        return today + timedelta(days=1)
    if normalized in {"day_after_tomorrow", "after_tomorrow"}:
        return today + timedelta(days=2)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _condition(code: object) -> str:
    try:
        return _WMO_CONDITIONS.get(int(str(code)), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


async def _resolve_coordinates(
    client: httpx.AsyncClient, location: str
) -> tuple[float, float, str] | None:
    response = await client.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "language": "en", "format": "json"},
    )
    _ = response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        return None
    result = results[0]
    label = ", ".join(
        part for part in (result.get("name"), result.get("country")) if part
    )
    return float(result["latitude"]), float(result["longitude"]), label or location


async def _resolve_configured_location_label(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> str | None:
    try:
        response = await client.get(
            _REVERSE_GEOCODING_URL,
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "zoom": 10,
                "addressdetails": 1,
            },
            headers={"User-Agent": "yuzu-companion/4.2"},
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        logger.warning("Configured weather location reverse geocoding failed")
        return None

    address = result.get("address") or {}
    label = next(
        (
            address.get(field)
            for field in (
                "city",
                "town",
                "municipality",
                "village",
                "county",
                "state",
            )
            if address.get(field)
        ),
        None,
    )
    return label or result.get("name") or None


def _daily_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    daily = data.get("daily") or {}
    keys = (
        "time",
        "weather_code",
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_probability_max",
        "wind_speed_10m_max",
    )
    rows = []
    for index, day in enumerate(daily.get("time") or []):
        row = {"date": day}
        for key in keys[1:]:
            values = daily.get(key) or []
            row[key] = values[index] if index < len(values) else None
        row["condition"] = _condition(row.get("weather_code"))
        rows.append(row)
    return rows


async def execute(
    arguments: dict[str, Any],
    session_id: str | None = None,
    tool_name: str = TOOL_NAME,
    user_id: str | None = None,
) -> dict[str, Any]:
    try:
        request = WeatherRequest(**arguments)
    except Exception as exc:
        return error_result(f"Invalid parameters: {exc}", TOOL_WEATHER)

    if request.date and _parse_date(request.date) is None:
        return error_result(
            "Invalid date. Use today, tomorrow, day_after_tomorrow, or YYYY-MM-DD."
        )

    if not user_id:
        return error_result("Missing user authentication. Cannot determine location.")

    profile = await Database.get_profile(user_id)
    if not profile:
        return error_result("User profile not found.")

    location_label = "Configured location"
    async with httpx.AsyncClient(timeout=10.0) as client:
        if request.location:
            resolved = await _resolve_coordinates(client, request.location)
            if not resolved:
                return error_result(
                    f"Could not find weather location: {request.location}"
                )
            latitude, longitude, location_label = resolved
        else:
            latitude = profile.get("location_lat")
            longitude = profile.get("location_lon")
            if latitude is None or longitude is None:
                return error_result(
                    "Weather location is not configured.",
                    TOOL_WEATHER,
                    category="configuration_error",
                    data={
                        "schema_kind": "weather",
                        "status": "location_required",
                        "location": None,
                    },
                )
            location_label = (
                await _resolve_configured_location_label(client, latitude, longitude)
                or location_label
            )

        selected_date = _parse_date(request.date)
        days = max(request.days, 1)
        if selected_date:
            offset = (selected_date - date.today()).days
            if offset < 0 or offset > 6:
                return error_result(
                    "Weather date must be within today and the next 6 days."
                )
            days = max(days, offset + 1)

        response = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        _ = response.raise_for_status()
        data = response.json()

    current = data.get("current") or {}
    current["condition"] = _condition(current.get("weather_code"))
    daily = _daily_rows(data)
    if selected_date:
        daily = [row for row in daily if row["date"] == selected_date.isoformat()]

    return ok_result(
        {
            "schema_kind": "weather",
            "source": "open-meteo",
            "location_label": location_label,
            "timezone": data.get("timezone"),
            "requested_date": selected_date.isoformat() if selected_date else None,
            "current": current,
            "daily": daily,
        },
        TOOL_WEATHER,
    )
