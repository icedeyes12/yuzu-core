import { chatStore } from "./store.js";

/**
 * EventRouter receives Server-Sent Events (SSE) and decodes them into semantic
 * events dispatched to the ConversationStore, replacing string accumulation.
 */
export class EventRouter {
	constructor() {
		this.activeViewSessionId = null;
		this.controllers = new Map();
	}

	/**
	 * Set the currently visible session to avoid processing background DOM events.
	 * (Note: ConversationStore handles its own state, this is for UI optimization).
	 */
	setActiveView(sessionId) {
		this.activeViewSessionId = sessionId;
		chatStore.sessionId = sessionId;
	}

	/**
	 * Attach a new AbortController to a session.
	 */
	registerStream(sessionId, controller) {
		this.controllers.set(sessionId, controller);
		chatStore.startGeneration();
	}

	/**
	 * Abort the stream for a session.
	 */
	cancelStream(sessionId) {
		const controller = this.controllers.get(sessionId);
		if (controller && !controller.signal.aborted) {
			controller.abort();
		}
		this.controllers.delete(sessionId);
		chatStore.finishGeneration();
	}

	/**
	 * Process a raw JSON chunk from the stream.
	 */
	handleEvent(sessionId, jsonString) {
		try {
			const event = JSON.parse(jsonString);
			const type = event.type || "token";

			if (type === "token") {
				chatStore.appendAssistantToken(event.chunk);
			} else if (type === "tool_call") {
				chatStore.updateToolCall({
					id: event.data?.id,
					name: event.data?.name,
					arguments_chunk: "",
					status: "started"
				});
			} else if (type === "tool_result") {
				chatStore.updateToolCall({
					id: event.data?.call_id,
					status: event.data?.ok ? "completed" : "error"
				});
				// Convert tool result into a distinct message for the store
				chatStore.appendMessage({
					id: `tool_${event.data?.call_id}`,
					role: "tool",
					tool_call_id: event.data?.call_id,
					name: event.data?.name,
					content: typeof event.data?.data === "string" ? event.data.data : JSON.stringify(event.data?.data)
				});
			} else if (type === "done") {
				this.controllers.delete(sessionId);
				chatStore.finishGeneration();
			}
		} catch (e) {
			console.error("[EventRouter] Failed to parse stream chunk", jsonString, e);
		}
	}
}

export const eventRouter = new EventRouter();
