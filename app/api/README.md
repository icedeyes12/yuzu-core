# API Routing Package

FastAPI APIRouter package for yuzu-companion web interface.

## Structure

```
app/api/
├── __init__.py    # Package init, exposes api_router
└── routes.py      # All /api/* endpoints
```

## Usage

In `web.py`:

```python
from app.api import api_router

app = FastAPI()
app.include_router(api_router, prefix="/api")
```

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/config` | GET | Frontend SSOT for vision models |
| `/api/send_message` | POST | Synchronous message handling |
| `/api/send_message_stream` | POST | Streaming message handling |
| `/api/get_profile` | GET | Profile data |
| `/api/update_profile` | POST | Update profile settings |
| `/api/providers` | GET | List available providers |
| `/api/providers/switch` | POST | Switch provider/model |
| `/api/providers/test` | POST | Test provider connectivity |
| `/api/sessions` | GET | List all sessions |
| `/api/sessions/create` | POST | Create new session |
| `/api/sessions/switch` | POST | Switch active session |
| `/api/sessions/rename` | POST | Rename session |
| `/api/sessions/delete` | POST | Delete session |
| `/api/memory_stats` | GET | Memory statistics |
| `/api/api_keys` | GET | List API keys |
| `/api/api_keys/add` | POST | Add API key |
| `/api/api_keys/delete` | POST | Delete API key |
| `/api/set_vision_model` | POST | Set vision model preference |
| `/api/upload_image` | POST | Upload image |
| `/api/generated_images/{filename}` | GET | Serve generated image |

## `/api/config` — Frontend SSOT

Returns dynamic configuration for the frontend, eliminating hardcoded values in JavaScript.

**Response:**

```json
{
  "status": "success",
  "vision": {
    "models_by_provider": {
      "chutes": [
        "Qwen/Qwen3.5-397B-A17B-TEE",
        "moonshotai/Kimi-K2.5-TEE",
        "moonshotai/Kimi-K2.6-TEE",
        "Qwen/Qwen3-VL-235B-A22B-Instruct"
      ],
      "openrouter": ["moonshotai/kimi-k2.5"]
    },
    "current_provider": "chutes",
    "current_model": "Qwen/Qwen3.5-397B-A17B-TEE"
  }
}
```

The frontend (`static/js/config.js`) fetches this on page load and populates the global `appConfig` variable.

## Session Tracking

Web session tracking is shared between `web.py` and `routes.py` via:

```python
# In routes.py
_web_session_tracker: Dict[str, bool] = {}

def set_session_tracker(tracker: Dict[str, bool]):
    global _web_session_tracker
    _web_session_tracker = tracker
```

```python
# In web.py
from app.api.routes import set_session_tracker

_web_session_tracker: Dict[str, bool] = {}
set_session_tracker(_web_session_tracker)
```

This allows HTML routes in `web.py` and API routes in `routes.py` to share session state.

## Pydantic Models

Request/response validation uses Pydantic models defined in `routes.py`:

- `MessageRequest`
- `StreamMessageRequest`
- `ApiKeyRequest`
- `ChutesKeyRequest`
- `SessionCreateRequest`
- `SessionSwitchRequest`
- `SessionRenameRequest`
- `SessionDeleteRequest`
- `ProviderSetRequest`
- `ProviderTestRequest`
- `VisionModelSetRequest`
- `LocationUpdateRequest`
- `GlobalKnowledgeUpdateRequest`

## Architecture Notes

- All endpoints are async (`async def`)
- Database operations use `app/db_pg_models_async.py`
- Business logic remains unchanged from original `web.py`
- No circular imports: `routes.py` imports from `app/`, not vice versa
