// FILE: static/js/modules/state.js
// DESCRIPTION: Global state management for chat interface

// ==================== GLOBAL STATE ====================
export let isProcessingMessage = false;
export const MESSAGES_PER_PAGE = 30;

// ==================== STREAMING STATE ====================
// Streaming ownership lives in EventRouter; this module only retains the
// UI processing flag for the input control.

// ==================== STATE SETTERS ====================
export function setIsProcessingMessage(value) {
	isProcessingMessage = value;
}

// ==================== MESSAGE ID TRACKING ====================
/**
 * Generate a unique message ID for DOM tracking.
 * Format: msg_<timestamp>_<random>
 */
export function generateMessageId() {
	return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Find an existing message element by its data-message-id.
 * @param {string} messageId - The message ID to find
 * @returns {HTMLElement|null}
 */
export function findMessageById(messageId) {
	if (!messageId) return null;
	return document.querySelector(`[data-message-id="${messageId}"]`);
}
