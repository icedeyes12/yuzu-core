// FILE: static/js/modules/stream-manager.js
// DESCRIPTION: Background SSE stream buffering independent of DOM

/**
 * CRITICAL: Manages SSE stream buffering INDEPENDENT of DOM.
 * The SSE reader loop ALWAYS buffers here. DOM is just a "view".
 *
 * Key principle: The stream never stops buffering just because we switched sessions.
 * The activeViewSessionId determines which session's buffer gets rendered to DOM.
 * 
 * SYNC MECHANISM: After stream completes, frontend syncs with backend to validate integrity.
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
		this._listeners = new Map(); // Event emitter for sync notifications
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
			
			// BACKGROUND SYNC: Validate buffer after completion
			this.syncWithBackend(sessionId);
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

	/**
	 * Background sync: Validate frontend buffer against backend after stream completion.
	 * This ensures frontend optimistic rendering matches backend's single source of truth.
	 * @param {number} sessionId - Session ID
	 * @returns {Promise<{valid: boolean, checksum: string, backend_length: number}>}
	 */
	async syncWithBackend(sessionId) {
		try {
			const response = await fetch(`/api/stream/${sessionId}/sync`);
			if (!response.ok) {
				console.warn(`[StreamManager] Sync failed for session ${sessionId}: HTTP ${response.status}`);
				return { valid: false };
			}

			const data = await response.json();
			const stream = this.streams.get(sessionId);

			if (stream && stream.buffer) {
				// Generate checksum from frontend
				const frontendChecksum = await this.generateChecksum(stream.buffer);
				const valid = frontendChecksum === data.checksum;

				console.log(
					`[StreamManager] Sync ${valid ? '✓' : '✗'} for session ${sessionId}`,
					`frontend: ${stream.buffer.length} chars, backend: ${data.length} chars`
				);

				// If mismatch, replace with backend version
				if (!valid && data.content) {
					console.warn(`[StreamManager] Buffer mismatch, replacing with backend version`);
					stream.buffer = data.content;
					// Trigger re-render if this is active view
					if (sessionId === this.activeViewSessionId) {
						this.emit('resync', sessionId, data.content);
					}
				}

				return { 
					valid,
					checksum: data.checksum,
					backend_length: data.length
				};
			}

			return { valid: false };
		} catch (error) {
			console.error(`[StreamManager] Sync error:`, error);
			return { valid: false };
		}
	}

	/**
	 * Generate checksum for buffer validation.
	 * Uses SHA-256 via Web Crypto API, returns first 16 hex chars.
	 * @param {string} content - Content to hash
	 * @returns {Promise<string>} Checksum string
	 */
	async generateChecksum(content) {
		try {
			const encoder = new TextEncoder();
			const data = encoder.encode(content);
			const hashBuffer = await crypto.subtle.digest('SHA-256', data);
			const hashArray = Array.from(new Uint8Array(hashBuffer));
			const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
			return hashHex.substring(0, 16); // First 16 chars only
		} catch (error) {
			console.error('[StreamManager] Checksum error:', error);
			return '';
		}
	}

	/**
	 * Event emitter for sync notifications.
	 */
	on(event, callback) {
		if (!this._listeners.has(event)) {
			this._listeners.set(event, []);
		}
		this._listeners.get(event).push(callback);
	}

	emit(event, ...args) {
		const callbacks = this._listeners.get(event) || [];
		callbacks.forEach(cb => cb(...args));
	}
}

// Create singleton instance
export const backgroundStreams = new BackgroundStreamManager();
