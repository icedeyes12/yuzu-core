import {
	serializeToolCallEvent,
	serializeToolResultEvent,
} from "./conversation-serializer.js";
import { cancelMessageFenceWork } from "./renderer/fence-lifecycle.js";
import { chatStore } from "./store.js";
import { domRenderer } from "./store-renderer.js";

/**
 * EventRouter receives Server-Sent Events (SSE) and decodes them into semantic
 * events dispatched to the ConversationStore, replacing string accumulation.
 */
export class EventRouter {
	constructor() {
		this.activeViewSessionId = null;
		this.controllers = new Map();
		this.activeTurnIds = new Map();
		this.pendingToolCalls = new Map();
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
		// Paint the indicator before the request can finish synchronously.
		domRenderer.flushPendingRender();
	}

	/**
	 * Abort the stream for a session.
	 */
	cancelStream(sessionId) {
		const controller = this.controllers.get(sessionId);
		if (controller && !controller.signal.aborted) controller.abort();
		this.controllers.delete(sessionId);
		this.activeTurnIds.delete(sessionId);
		if (chatStore.sessionId === sessionId) {
			cancelMessageFenceWork();
			chatStore.finishGeneration();
			domRenderer.flushPendingRender();
		}
	}

	/**
	 * Complete a stream through the same terminal path regardless of whether
	 * the server emits `done` or the fetch reader ends cleanly without it.
	 */
	finishStream(sessionId) {
		if (sessionId !== this.activeViewSessionId) return;
		this.controllers.delete(sessionId);
		this.activeTurnIds.delete(sessionId);
		for (const [callId, pendingCall] of this.pendingToolCalls) {
			if (pendingCall.sessionId === sessionId)
				this.pendingToolCalls.delete(callId);
		}
		if (chatStore.isGenerating) chatStore.finishGeneration();
		domRenderer.flushPendingRender();
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
				if (content) {
					// If the last assistant message has completed tool_calls,
					// the model is now on a new pass — start a fresh bubble
					// so the post-tool response renders below the tool results
					// (matching the DB structure after reload).
					const active = chatStore._getActiveAssistant();
					if (active?.toolCalls?.length > 0) {
						active.metadata.isFrozen = true;
						chatStore.beginAssistantMessage();
					}
					chatStore.appendAssistantToken(content);
				}
				return;
			}

			if (type === "tool_call") {
				const data =
					event.data && typeof event.data === "object" ? event.data : event;
				const toolCall = serializeToolCallEvent(data);
				if (!toolCall) {
					chatStore.setError("The server sent an invalid tool-call event.");
					return;
				}
				if (data.turn_id) this.activeTurnIds.set(sessionId, data.turn_id);
				this.pendingToolCalls.set(toolCall.id, {
					sessionId,
					name: toolCall.name,
				});
				chatStore.updateToolCall({
					...toolCall,
					arguments_chunk: toolCall.arguments,
				});
				return;
			}

			if (type === "tool_result") {
				const data =
					event.data && typeof event.data === "object" ? event.data : event;
				const toolResult = serializeToolResultEvent(data);
				if (!toolResult) {
					chatStore.setError("The server sent an invalid tool-result event.");
					return;
				}
				const pendingCall = this.pendingToolCalls.get(
					toolResult.toolResponse.callId,
				);
				if (
					data.turn_id &&
					this.activeTurnIds.get(sessionId) !== data.turn_id &&
					!pendingCall
				)
					return;
				if (!pendingCall) return;
				this.pendingToolCalls.delete(toolResult.toolResponse.callId);
				chatStore.updateToolCall({
					id: toolResult.toolResponse.callId,
					status: toolResult.toolResponse.status,
				});
				chatStore.appendMessage(toolResult);
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
				if (event.turn_id) this.activeTurnIds.set(sessionId, event.turn_id);
				this.finishStream(sessionId);
				return;
			}

			chatStore.setError(`Unknown stream event: ${type}`);
		} catch (_error) {
			chatStore.setError("The server sent invalid stream data.");
		}
	}
}

export const eventRouter = new EventRouter();
