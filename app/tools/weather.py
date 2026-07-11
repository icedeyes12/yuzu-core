import logging
import httpx
from pydantic import BaseModel, ConfigDict
from app.db import Database
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)


class WeatherRequest(BaseModel):
    # No params needed from LLM if reading from DB, but kept as optional
    # in case LLM wants to check another location explicitly.
    model_config = ConfigDict(extra="forbid")


TOOL_NAME = "weather"
TOOL_WEATHER = ToolDefinition(
    name=TOOL_NAME,
    description="Fetch current weather. Uses user's configured location by default.",
    role="info_tools",
    parameters=[],  # No parameters required
    needs_session=True,  # Need session to infer user_id for location
)

TOOL_DEFINITION = {"weather": TOOL_WEATHER}


async def execute(
    arguments: dict,
    session_id: str | None = None,
    tool_name: str = "weather",
    user_id: str | None = None,
) -> dict:
    partner_name = "Yuzu"

    # 1. Validation (Pydantic)
    try:
        WeatherRequest(**arguments)
    except Exception as e:
        return error_result(
            f"Invalid parameters: {e}", TOOL_WEATHER, "weather_fetch", partner_name
        )

    # 2. Extract Location
    if not user_id:
        return error_result(
            "Missing user authentication. Cannot determine location.",
            TOOL_WEATHER,
            "weather_fetch",
            partner_name,
        )

    profile = await Database.get_profile(user_id)
    if not profile:
        return error_result(
            "User profile not found.", TOOL_WEATHER, "weather_fetch", partner_name
        )

    latitude = profile.get("location_lat")
    longitude = profile.get("location_lon")

    if latitude is None or longitude is None:
        return error_result(
            "Location missing. User has not enabled location in settings.",
            TOOL_WEATHER,
            "weather_fetch",
            partner_name,
        )

    # 3. Execution
    url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,weather_code&timezone=auto"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            # Return pure structure
            return ok_result({
                "source": "open-meteo",
                "current": data.get("current", {})
            })
            
    except Exception as e:
        logger.error(f"[weather] Failed to fetch data: {e}")
        return error_result(f"Failed to fetch weather data: {e}")
