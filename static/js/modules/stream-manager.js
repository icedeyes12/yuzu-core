// FILE: static/js/modules/stream-manager.js
// DESCRIPTION: Background SSE stream buffering independent of DOM

/**
 * CRITICAL: Manages SSE stream buffering INDEPENDENT of DOM.
 * The SSE reader loop ALWAYS buffers here. DOM is just a "view".
 *
 * Key principle: The stream never stops buffering just because we switched sessions.
 * The activeViewSessionId determines which session's buffer gets rendered to DOM.
 */
export class BackgroundStreamManager {
	constructor() {
		// Map of sessionId -> {
		//   buffer: string,           // Accumulated text chunks
		//   controller: AbortController,
		//   messageId: string,        // DOM tracking ID
		//   isActive: boolean,        // Stream still running?
		//   isComplete: boolean       // Stream finished?
		// }
		this.streams = new Map();
		this.activeViewSessionId = null; // Which session is currently visible in DOM
	}

	/**
	 * Start a new stream buffer for a session.
	 * @param {number} sessionId - Session ID
	 * @param {AbortController} controller - AbortController for the stream
	 * @param {string} messageId - Unique message ID for DOM tracking
	 */
	startStream(sessionId, controller, messageId) {
		this.streams.set(sessionId, {
			buffer: "",
			controller,
			messageId,
			isActive: true,
			isComplete: false,
		});
		console.log(
			`[StreamManager] Started stream for session ${sessionId}, messageId: ${messageId}`,
		);
	}

	/**
	 * Append a chunk to the buffer. ALWAYS called by SSE reader, regardless of active session.
	 * @param {number} sessionId - Session ID
	 * @param {string} chunk - Text chunk to append
	 * @returns {string|null} The full accumulated text, or null if stream not found
	 */
	appendChunk(sessionId, chunk) {
		const stream = this.streams.get(sessionId);
		if (!stream) {
			console.warn(`[StreamManager] No stream found for session ${sessionId}`);
			return null;
		}

		stream.buffer += chunk;

		// Only return buffer if this is the active view
		if (sessionId === this.activeViewSessionId) {
			return stream.buffer;
		}

		// Stream is running in background - don't return, just buffer
		console.log(
			`[StreamManager] Background buffering for session ${sessionId}, buffer length: ${stream.buffer.length}`,
		);
		return null;
	}

	/**
	 * Get the current buffer for a session.
	 * @param {number} sessionId - Session ID
	 * @returns {string} The accumulated buffer
	 */
	getBuffer(sessionId) {
		const stream = this.streams.get(sessionId);
		return stream?.buffer || "";
	}

	/**
	 * Mark a stream as complete.
	 * @param {number} sessionId - Session ID
	 */
	completeStream(sessionId) {
		const stream = this.streams.get(sessionId);
		if (stream) {
			stream.isActive = false;
			stream.isComplete = true;
			console.log(`[StreamManager] Completed stream for session ${sessionId}`);
		}
	}

	/**
	 * Cancel a stream.
	 * @param {number} sessionId - Session ID
	 */
	cancelStream(sessionId) {
		const stream = this.streams.get(sessionId);
		if (stream) {
			if (stream.controller && !stream.controller.signal.aborted) {
				stream.controller.abort();
			}
			this.streams.delete(sessionId);
			console.log(`[StreamManager] Cancelled stream for session ${sessionId}`);
		}
	}

	/**
	 * Check if a session has an active (still running) stream.
	 * @param {number} sessionId - Session ID
	 * @returns {boolean}
	 */
	hasActiveStream(sessionId) {
		const stream = this.streams.get(sessionId);
		return stream?.isActive === true;
	}

	/**
	 * Check if a session has any stream (active or completed).
	 * @param {number} sessionId - Session ID
	 * @returns {boolean}
	 */
	hasStream(sessionId) {
		return this.streams.has(sessionId);
	}

	/**
	 * Get stream info.
	 * @param {number} sessionId - Session ID
	 * @returns {object|null}
	 */
	getStream(sessionId) {
		return this.streams.get(sessionId) || null;
	}

	/**
	 * Set which session is currently visible in DOM.
	 * @param {number} sessionId - Session ID
	 */
	setActiveView(sessionId) {
		this.activeViewSessionId = sessionId;
	}

	/**
	 * Check if ANY session is currently generating.
	 * @returns {boolean}
	 */
	isAnyGenerating() {
		for (const stream of this.streams.values()) {
			if (stream.isActive) return true;
		}
		return false;
	}
}

// Create singleton instance
export const backgroundStreams = new BackgroundStreamManager();
