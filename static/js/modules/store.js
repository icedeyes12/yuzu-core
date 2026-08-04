/**
 * FILE: static/js/modules/store.js
 * DESCRIPTION: Single Source of Truth for the active conversation state.
 * Implements an event-driven, strictly one-way data flow architecture.
 */

import {
	serializeConversationHistory,
	serializeConversationMessage,
} from "./conversation-serializer.js";

export class ConversationStore {
	constructor() {
		this.sessionId = null;
		this.messages = []; // Array of message objects (ConversationEvent)
		this.subscribers = new Set();
		this.isGenerating = false;
		this.error = null;
	}

	/**
	 * Subscribe to state changes.
	 * @param {Function} callback - Called when state changes.
	 * @returns {Function} Unsubscribe function.
	 */
	subscribe(callback) {
		this.subscribers.add(callback);
		return () => this.subscribers.delete(callback);
	}

	/**
	 * Notify all subscribers of a state change.
	 */
	_notify(eventObj = { type: "update" }) {
		this.subscribers.forEach((cb) => {
			cb(this.messages, this.isGenerating, this.error, eventObj);
		});
	}

	/**
	 * Load full history (usually from /api/v1/chat_history).
	 * Replaces current state.
	 * @param {string} sessionId
	 * @param {Array} history
	 * @param {boolean} hasMore
	 */
	loadHistory(sessionId, history, hasMore = false) {
		this.sessionId = sessionId;
		this.messages = serializeConversationHistory(history, { isFrozen: true });
		this.hasMoreOlder = hasMore;
		this.isGenerating = false;
		this.error = null;
		this._notify({ type: "reset" });
	}

	/**
	 * Prepend older history chunk (upward scroll).
	 * @param {Array} olderHistory
	 * @param {boolean} hasMore
	 */
	prependHistory(olderHistory, hasMore = false) {
		if (!olderHistory?.length) {
			this.hasMoreOlder = hasMore;
			return;
		}
		const serialized = serializeConversationHistory(olderHistory, {
			isFrozen: true,
		});
		// Filter out duplicate message IDs
		const existingIds = new Set(this.messages.map((m) => m.id));
		const uniqueNew = serialized.filter((m) => !existingIds.has(m.id));
		this.messages = [...uniqueNew, ...this.messages];
		this.hasMoreOlder = hasMore;
		this._notify({ type: "prepend", addedCount: uniqueNew.length });
	}

	/**
	 * Start a new assistant generation stream.
	 */
	startGeneration() {
		this.isGenerating = true;
		this.error = null;
		this._notify();
	}

	/**
	 * Finish the current assistant generation stream.
	 */
	finishGeneration() {
		this.isGenerating = false;

		// Freeze every message still owned by the completed turn. A tool result
		// can be appended after the assistant message, so inspecting only the
		// final array item leaves the assistant bubble unfrozen.
		for (const message of this.messages) {
			if (message.role === "assistant" || message.role === "tool") {
				message.metadata.isFrozen = true;
			}
		}

		this._notify();
	}

	setError(error) {
		this.error = error ? String(error) : null;
		this.isGenerating = false;
		this._notify();
	}

	/**
	 * Append a new message to the conversation.
	 * @param {Object} message - Raw message object
	 */
	appendMessage(message) {
		const normalized = serializeConversationMessage(message);
		if (!normalized) return;
		const existingIndex = this.messages.findIndex(
			(existing) => existing.id === normalized.id,
		);
		if (existingIndex >= 0) {
			this.messages[existingIndex] = {
				...this.messages[existingIndex],
				...normalized,
			};
		} else {
			this.messages.push(normalized);
		}
		this._notify();
	}

	/**
	 * Get the active (unfrozen) assistant message from the end of messages list.
	 * Falls back to the last message if no active assistant is found.
	 * @private
	 */
	_getActiveAssistant() {
		for (let i = this.messages.length - 1; i >= 0; i--) {
			const msg = this.messages[i];
			if (msg.role === "assistant" && !msg.metadata.isFrozen) return msg;
		}
		return null;
	}

	/**
	 * Append a text chunk to the active assistant message in the store.
	 * @param {string} textChunk
	 */
	appendAssistantToken(textChunk) {
		if (typeof textChunk !== "string" || !textChunk) return;
		const activeMsg = this._getActiveAssistant();
		if (!activeMsg) return;

		if (activeMsg.role !== "assistant" || activeMsg.metadata.isFrozen) {
			return;
		}

		activeMsg.content = (activeMsg.content || "") + textChunk;
		this._notify();
	}

	beginAssistantMessage() {
		this.appendMessage({ role: "assistant", content: "" });
	}

	/**
	 * Update an active tool call's state on the active assistant message.
	 * @param {Object} toolPayload - { id, name, arguments_chunk, status }
	 */
	updateToolCall(toolPayload) {
		const activeMsg = this._getActiveAssistant();
		if (!activeMsg) return;

		if (activeMsg.role !== "assistant" || activeMsg.metadata.isFrozen) {
			return;
		}

		// Ensure tool_calls array exists
		if (!activeMsg.toolCalls) {
			activeMsg.toolCalls = [];
		}

		const existingTool = activeMsg.toolCalls.find(
			(t) => t.id === toolPayload.id,
		);
		if (existingTool) {
			if (toolPayload.arguments_chunk) {
				existingTool.arguments = toolPayload.arguments_chunk;
			}
			if (toolPayload.status) {
				existingTool.status = toolPayload.status;
			}
		} else {
			// Create new
			activeMsg.toolCalls.push({
				id: toolPayload.id,
				name: toolPayload.name,
				arguments: toolPayload.arguments_chunk || "",
				status: toolPayload.status || "started",
			});
		}

		this._notify();
	}

	/**
	 * Find a message by ID.
	 * @param {string} id
	 */
	getMessageById(id) {
		return this.messages.find((m) => m.id === id) || null;
	}
}

// Global singleton instance for the application
export const chatStore = new ConversationStore();
