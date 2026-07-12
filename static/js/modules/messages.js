// FILE: static/js/modules/messages.js
// DESCRIPTION: Message creation, rendering, and formatting utilities

import { findMessageById } from "./state.js";

/**
 * Create a message element with proper structure.
 * @param {string} role - 'user' or 'ai'
 * @param {string} content - Message content
 * @param {string|null} timestamp - Optional timestamp
 * @returns {HTMLElement} The message element
 */
export function createMessageElement(role, content, timestamp = null) {
	const msg = document.createElement("div");
	msg.className = `message ${role}-message`;

	const bubble = document.createElement("div");
	bubble.className = "message-bubble";

	// Header INSIDE the bubble for tool messages, else hidden/omitted
	if (role === "tool" || role === "event_log") {
		const header = document.createElement("div");
		header.className = "message-header";
		header.textContent = role === "tool" ? "Tool Output" : "System Event";
		bubble.appendChild(header);
	}

	const contentContainer = document.createElement("div");
	contentContainer.className = "message-content markdown-body";

	// Initial render
	if (window.renderMessageContent) {
		contentContainer.innerHTML = window.renderMessageContent(content, role === "user");
	} else {
		contentContainer.textContent = content == null ? "" : String(content);
	}

	bubble.appendChild(contentContainer);
	msg.appendChild(bubble);

	// Footer OUTSIDE the bubble (timestamp + copy button)
	const footer = document.createElement("div");
	footer.className = `message-footer message-footer--${role}`;

	const timeDiv = document.createElement("div");
	timeDiv.className = "timestamp";
	timeDiv.textContent = timestamp || getCurrentTime24h();
	footer.appendChild(timeDiv);

	const copyBtn = document.createElement("button");
	copyBtn.className = "copy-message-btn";
	copyBtn.setAttribute("data-action", "copy-message");
	copyBtn.setAttribute("data-message-content", content);
	copyBtn.title = "Copy full message";
	copyBtn.innerHTML = `
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
			<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
		</svg>
	`;
	footer.appendChild(copyBtn);

	msg.appendChild(footer);

	return msg;
}

/**
 * Add a message to the chat container.
 * @param {string} role - 'user' or 'ai'
 * @param {string} content - Message content
 * @param {string|null} timestamp - Optional timestamp
 * @param {boolean} isHistory - Whether this is from history (skip scroll)
 * @returns {HTMLElement|null} The message element
 */
export function addMessage(role, content, timestamp = null, isHistory = false) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) {
		console.error("Cannot add message: chat container not found!");
		return null;
	}

	const msg = createMessageElement(role, content, timestamp);
	chatContainer.appendChild(msg);

	if (!isHistory) {
		setTimeout(() => {
			// Import scrollToBottom dynamically to avoid circular dependency
			import("./scroll.js").then(({ scrollToBottom }) => {
				scrollToBottom();
			});
			// Update layout after message append
			if (typeof window.updateDynamicLayout === "function") {
				window.updateDynamicLayout();
			}
		}, 50);
	}

	console.log(`Added ${role} message`);
	return msg;
}

/**
 * Copy full message content to clipboard.
 * @param {string} content - Content to copy
 */
export function copyFullMessage(content) {
	// Uses centralized ClipboardUtils from renderer.js for consistent behavior
	if (typeof ClipboardUtils !== "undefined") {
		ClipboardUtils.copyText(content);
	} else {
		// Fallback for cases where renderer.js hasn't loaded
		navigator.clipboard
			.writeText(content)
			.then(() => {
				console.log("Message copied to clipboard");
			})
			.catch((err) => {
				console.error("Failed to copy message:", err);
			});
	}
}

/**
 * Check if a role is renderable in history.
 * @param {string} role - Message role
 * @returns {boolean}
 */
export function isRenderableHistoryRole(role) {
	return (
		role === "user" ||
		role === "assistant" ||
		role === "tool" ||
		(typeof role === "string" && role.endsWith("_tools"))
	);
}

/**
 * Render message content through the renderer pipeline.
 * @param {string} rawText - Raw message text
 * @param {boolean} isUser - Whether this is a user message
 * @returns {string} Rendered HTML
 */
export function renderMessageContent(rawText, isUser = false) {
	const safeText = String(rawText ?? "");
	console.log("User raw message:", JSON.stringify(safeText));
	const escapedText = escapeMessageHtml(safeText);
	try {
		let processed = safeText;
		return escapedText;
	} catch (e) {
		console.error("Render error:", e, safeText);
		return `<pre class="render-error">${escapedText}</pre>`;
	}
}

/**
 * Escape HTML entities in text.
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
export function escapeMessageHtml(text) {
	return String(text).replace(
		/[&<>"']/g,
		(c) =>
			({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
				c
			],
	);
}

/**
 * Format timestamp for display.
 * @param {string} timestamp - ISO timestamp string
 * @returns {string} Formatted time (HH:MM)
 */
export function formatTimestamp(timestamp) {
	if (!timestamp) return "";

	try {
		const dbDate = new Date(timestamp);
		let hours = dbDate.getHours();
		let minutes = dbDate.getMinutes();

		hours = hours < 10 ? `0${hours}` : hours;
		minutes = minutes < 10 ? `0${minutes}` : minutes;

		return `${hours}:${minutes}`;
	} catch (e) {
		console.error("Error formatting timestamp:", e, timestamp);
		return timestamp;
	}
}

/**
 * Get current time in 24h format.
 * @returns {string} Time as HH:MM
 */
export function getCurrentTime24h() {
	const now = new Date();
	let hours = now.getHours();
	let minutes = now.getMinutes();
	hours = hours < 10 ? `0${hours}` : hours;
	minutes = minutes < 10 ? `0${minutes}` : minutes;
	return `${hours}:${minutes}`;
}

// Re-export findMessageById for convenience
export { findMessageById };
