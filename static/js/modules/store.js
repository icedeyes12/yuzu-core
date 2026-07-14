/**
 * FILE: static/js/modules/store.js
 * DESCRIPTION: Single Source of Truth for the active conversation state.
 * Implements an event-driven, strictly one-way data flow architecture.
 */

export class ConversationStore {
	constructor() {
		this.sessionId = null;
		this.messages = []; // Array of message objects (ConversationEvent)
		this.subscribers = new Set();
		this.isGenerating = false;
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
	_notify() {
		this.subscribers.forEach((cb) => cb(this.messages, this.isGenerating));
	}

	/**
	 * Load full history (usually from /api/chat_history).
	 * Replaces current state.
	 * @param {string} sessionId
	 * @param {Array} history
	 */
	loadHistory(sessionId, history) {
		this.sessionId = sessionId;
		this.messages = history.map((msg) => this._normalizeMessage(msg));
		this.isGenerating = false;
		this._notify();
	}

	/**
	 * Start a new assistant generation stream.
	 */
	startGeneration() {
		this.isGenerating = true;
		this._notify();
	}

	/**
	 * Finish the current assistant generation stream.
	 */
	finishGeneration() {
		this.isGenerating = false;
		
		// Freeze the last message if it belongs to the assistant
		if (this.messages.length > 0) {
			const lastMsg = this.messages[this.messages.length - 1];
			if (lastMsg.role === "assistant" || lastMsg.role === "tool") {
				lastMsg.isFrozen = true;
			}
		}
		
		this._notify();
	}

	/**
	 * Append a new message to the conversation.
	 * @param {Object} message - Raw message object
	 */
	appendMessage(message) {
		this.messages.push(this._normalizeMessage(message));
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
			if (msg.role === "assistant" && !msg.isFrozen) {
				return msg;
			}
		}
		return this.messages.length > 0 ? this.messages[this.messages.length - 1] : null;
	}

	/**
	 * Append a text chunk to the active assistant message in the store.
	 * @param {string} textChunk
	 */
	appendAssistantToken(textChunk) {
		const activeMsg = this._getActiveAssistant();
		if (!activeMsg) return;

		if (activeMsg.role !== "assistant" || activeMsg.isFrozen) {
			console.warn("[Store] Cannot append token to frozen or non-assistant message.", activeMsg);
			return;
		}

		activeMsg.content = (activeMsg.content || "") + textChunk;
		this._notify();
	}

	/**
	 * Update an active tool call's state on the active assistant message.
	 * @param {Object} toolPayload - { id, name, arguments_chunk, status }
	 */
	updateToolCall(toolPayload) {
		const activeMsg = this._getActiveAssistant();
		if (!activeMsg) return;

		if (activeMsg.role !== "assistant" || activeMsg.isFrozen) {
			console.warn("[Store] Cannot update tool call on frozen or non-assistant message.", activeMsg);
			return;
		}

		// Ensure tool_calls array exists
		if (!activeMsg.tool_calls) {
			activeMsg.tool_calls = [];
		}

		const existingTool = activeMsg.tool_calls.find(t => t.id === toolPayload.id);
		if (existingTool) {
			// Update existing
			if (toolPayload.arguments_chunk) {
				existingTool.arguments += toolPayload.arguments_chunk;
			}
			if (toolPayload.status) {
				existingTool.status = toolPayload.status;
			}
		} else {
			// Create new
			activeMsg.tool_calls.push({
				id: toolPayload.id,
				name: toolPayload.name,
				arguments: toolPayload.arguments_chunk || "",
				status: toolPayload.status || "started"
			});
		}

		this._notify();
	}

	/**
	 * Find a message by ID.
	 * @param {string} id
	 */
	getMessageById(id) {
		return this.messages.find(m => m.id === id) || null;
	}

	/**
	 * Internal: Normalize an incoming raw dict into a consistent internal model.
	 */
	_normalizeMessage(raw) {
		return {
			id: raw.id || `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
			turn_id: raw.turn_id || null,
			role: raw.role || "unknown",
			content: raw.content || "",
			attachments: Array.isArray(raw.attachments) ? raw.attachments : [],
			tool_calls: Array.isArray(raw.tool_calls) ? [...raw.tool_calls] : [],
			tool_call_id: raw.tool_call_id || null,
			name: raw.name || null,
			isFrozen: raw.isFrozen || false, // Once true, Renderer assumes immutable
			timestamp: raw.timestamp || new Date().toISOString()
		};
	}
}

// Global singleton instance for the application
export const chatStore = new ConversationStore();
