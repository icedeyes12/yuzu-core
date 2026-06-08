# Streaming State Machine

The Yuzu-Companion backend handles real-time Server-Sent Events (SSE) streaming with a robust state machine that persists beyond individual HTTP requests. This architecture prevents data loss when the frontend disconnects mid-generation.

## Core Component: `StreamManager` (`app/stream_manager.py`)

The `StreamManager` is responsible for caching and managing the active state of an LLM generation sequence.

### Streaming Lifecycle

1. **Initialization (Start Stream)**
   - When a user sends a message via `POST /api/send_message_stream`, the `ChatService` invokes `StreamManager.start_stream()`.
   - The stream is registered globally using the `session_id` as the key.
   - An asynchronous generator task is spawned in the background to handle the actual LLM dispatch and response chunking.

2. **Buffering & Yielding**
   - As the LLM yields chunks, the `StreamBuffer` stores every chunk in its internal history (`self.full_content`).
   - Simultaneously, chunks are pushed to an `asyncio.Queue` for the active HTTP response to consume.
   - The `StreamFilter` (`app/commands.py`) acts as a middleware to detect `<command>` tags and suppress them from being yielded to the user interface.

3. **Client Disconnection**
   - If the client closes the browser or the connection drops, the background LLM task **continues generating**.
   - Chunks are still appended to the `StreamBuffer` history, but the queue pushing may drop if no consumers exist.

4. **Reconnection & State Recovery**
   - When the UI reconnects or requests a profile reload, it fetches the active session history.
   - If an active stream exists for that `session_id`, the `StreamManager` injects the currently buffered `full_content` into the history payload.
   - This ensures the UI instantly recovers the in-flight assistant response without waiting for the original socket.

5. **Finalization & Persistence**
   - Once generation is complete (or if the LLM errors out), `finish()` is called.
   - The final `full_content` is permanently written to the PostgreSQL database.
   - The stream is kept in cache for a 15-minute TTL before being garbage collected to allow any lagging UI requests to safely catch up.