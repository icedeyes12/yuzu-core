import { chatStore } from "./store.js";

/**
 * EventRouter receives Server-Sent Events (SSE) and decodes them into semantic
 * events dispatched to the ConversationStore, replacing string accumulation.
 */
export class EventRouter {
	constructor() {
		this.activeViewSessionId = null;
		this.controllers = new Map();
		this.activeTurnIds = new Map();
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
	registerStream(sessionId, controller, turnId = null) {
		this.controllers.set(sessionId, controller);
		if (turnId) this.activeTurnIds.set(sessionId, turnId);
		chatStore.startGeneration();
	}

	/**
	 * Abort the stream for a session.
	 */
	cancelStream(sessionId) {
		const controller = this.controllers.get(sessionId);
		if (controller && !controller.signal.aborted) controller.abort();
		this.controllers.delete(sessionId);
		this.activeTurnIds.delete(sessionId);
		if (chatStore.sessionId === sessionId) chatStore.finishGeneration();
	}

	/**
	 * Process a raw JSON chunk from the stream.
	 */
	handleEvent(sessionId, jsonString) {
		if (sessionId !== this.activeViewSessionId) return;

		try {
			const event = JSON.parse(jsonString);
			const type = event.type;
			if (!type) {
				chatStore.setError("The server sent an event without a type.");
				return;
			}

			if (type === "token") {
				const content =
					typeof event.content === "string" ? event.content : event.chunk;
				if (typeof content !== "string") {
					chatStore.setError("The server sent an invalid token event.");
					return;
				}
				if (content) chatStore.appendAssistantToken(content);
				return;
			}

			if (type === "tool_call") {
				const data =
					event.data && typeof event.data === "object" ? event.data : event;
				if (!data?.id || !data.name) {
					chatStore.setError("The server sent an invalid tool-call event.");
					return;
				}
				if (data.turn_id) this.activeTurnIds.set(sessionId, data.turn_id);
				chatStore.updateToolCall({
					id: data.id,
					name: data.name,
					arguments_chunk: JSON.stringify(data.arguments || {}),
					status: "started",
				});
				return;
			}

			if (type === "tool_result") {
				const data =
					event.data && typeof event.data === "object" ? event.data : event;
				if (!data?.call_id || !data.name) {
					chatStore.setError("The server sent an invalid tool-result event.");
					return;
				}
				if (data.turn_id && this.activeTurnIds.get(sessionId) !== data.turn_id)
					return;
				chatStore.updateToolCall({
					id: data.call_id,
					status: data.ok === false ? "error" : "completed",
				});
				chatStore.appendMessage({
					id: `tool_${data.call_id}`,
					role: "tool",
					tool_call_id: data.call_id,
					name: data.name || "unknown",
					content: JSON.stringify(data),
					isFrozen: true,
				});
				return;
			}

			if (type === "error") {
				this.controllers.delete(sessionId);
				this.activeTurnIds.delete(sessionId);
				chatStore.setError(
					event.message || event.error || "The stream failed.",
				);
				return;
			}

			if (type === "done") {
				if (
					!event.turn_id ||
					event.turn_id !== this.activeTurnIds.get(sessionId)
				)
					return;
				this.controllers.delete(sessionId);
				this.activeTurnIds.delete(sessionId);
				chatStore.finishGeneration();
				return;
			}

			chatStore.setError(`Unknown stream event: ${type}`);
		} catch (_error) {
			chatStore.setError("The server sent invalid stream data.");
		}
	}
}

export const eventRouter = new EventRouter();
