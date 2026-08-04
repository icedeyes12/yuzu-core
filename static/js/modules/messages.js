// FILE: static/js/modules/messages.js
// DESCRIPTION: Message creation, rendering, and formatting utilities

import { renderRuntimeIcon } from "../runtime-icon-renderer.js";
import { findMessageById } from "./state.js";
import { safeImagePath } from "./tool-renderer/dom-utils.js";

/**
 * Create a message element with proper structure.
 * @param {string} role - 'user' or 'ai'
 * @param {string} content - Message content
 * @param {string|null} timestamp - Optional timestamp
 * @returns {HTMLElement} The message element
 */
export function createMessageElement(
	role,
	content,
	timestamp = null,
	{ suppressCopy = false } = {},
) {
	const msg = document.createElement("div");
	msg.className = `message ${role}-message`;

	const bubble = document.createElement("div");
	bubble.className = "message-bubble";

	// System events get a small label; tool results provide their own context.
	if (role === "event_log") {
		const header = document.createElement("div");
		header.className = "message-header";
		header.textContent = "System Event";
		bubble.appendChild(header);
	}

	const contentContainer = document.createElement("div");
	contentContainer.className = "message-content markdown-body";

	// Initial render
	if (role === "tool") {
		// Try to parse the content as JSON for the tool renderer
		try {
			// Find the actual tool name from a passed message object (handled by store-renderer later)
			// But since createMessageElement doesn't get the full object, store-renderer handles tool rendering
			contentContainer.innerHTML = renderMessageContent(content, false);
		} catch (_e) {
			contentContainer.innerHTML = renderMessageContent(content, false);
		}
	} else {
		contentContainer.innerHTML = renderMessageContent(content, role === "user");
	}

	bubble.appendChild(contentContainer);
	msg.appendChild(bubble);

	// Footer OUTSIDE the bubble (timestamp + copy button)
	const footer = document.createElement("div");
	footer.className = `message-footer message-footer--${role}`;

	const timeDiv = document.createElement("div");
	timeDiv.className = "timestamp";
	timeDiv.textContent = timestamp
		? formatTimestamp(timestamp)
		: getCurrentTime24h();
	footer.appendChild(timeDiv);

	if (role !== "tool" && !suppressCopy) {
		const copyBtn = document.createElement("button");
		copyBtn.className = "copy-message-btn";
		copyBtn.setAttribute("data-action", "copy-message");
		copyBtn.setAttribute("data-message-content", content);
		copyBtn.title = "Copy full message";
		copyBtn.innerHTML =
			renderRuntimeIcon("copy", {
				size: 16,
				strokeWidth: 2,
			}) || "";
		footer.appendChild(copyBtn);
	}

	msg.appendChild(footer);

	return msg;
}

/**
 * Copy full message content to clipboard.
 * @param {string} content - Content to copy
 */
export function copyFullMessage(content) {
	if (navigator.clipboard?.writeText) {
		void navigator.clipboard.writeText(content).catch(() => {});
	}
}

function setCopyFeedback(button, label) {
	button.classList.add("copied");
	button.setAttribute("aria-label", label);
	window.setTimeout(() => {
		button.classList.remove("copied");
		button.setAttribute(
			"aria-label",
			button.dataset.action === "copy-tool-output"
				? "Copy terminal output"
				: button.dataset.action === "copy-tool-prompt"
					? "Copy image prompt"
					: "Copy message",
		);
	}, 1200);
}

function handleCopyMessageClick(event) {
	const button = event.target.closest(
		'[data-action="copy-message"], [data-action="copy-tool-output"], [data-action="copy-tool-prompt"]',
	);
	if (!button || button.disabled) return;
	event.preventDefault();
	const isToolOutput = button.dataset.action === "copy-tool-output";
	const isToolPrompt = button.dataset.action === "copy-tool-prompt";
	const outputElement = isToolOutput
		? button
				.closest(".tool-card__output")
				?.querySelector(".tool-card__pre code")
		: isToolPrompt
			? button
					.closest(".image-card__prompt")
					?.querySelector(".image-card__prompt-code code")
			: null;
	const content =
		isToolOutput || isToolPrompt
			? outputElement?.textContent || ""
			: button.getAttribute("data-message-content") || "";
	if (!navigator.clipboard?.writeText) return;
	void navigator.clipboard.writeText(content).then(
		() => setCopyFeedback(button, "Copied"),
		() => {},
	);
}

let copyBindingInitialized = false;

export function initializeMessageActions() {
	if (copyBindingInitialized) return;
	document.addEventListener("click", handleCopyMessageClick);
	copyBindingInitialized = true;
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
export function renderMessageContent(rawText, _isUser = false) {
	const safeText = String(rawText ?? "");

	try {
		// Use marked if available
		if (window.marked) {
			// If fence renderer is already installed (by store-renderer.js), just parse.
			// Otherwise configure basic options (fence renderer will be installed later).
			if (!window._fenceRendererInstalled && !window._markedConfigured) {
				window.marked.setOptions({
					breaks: true,
					gfm: true,
					sanitize: false,
				});
				window._markedConfigured = true;
			}
			const startedAt = performance.now();
			const rendered = window.marked.parse(safeText);
			window.__yuzuMarkdownMetrics ??= { parseCount: 0, parseDurationMs: 0 };
			window.__yuzuMarkdownMetrics.parseCount += 1;
			window.__yuzuMarkdownMetrics.parseDurationMs +=
				performance.now() - startedAt;
			return rendered.replace(
				/(<img\b[^>]*\bsrc=["'])([^"']+)(["'])/gi,
				(_match, prefix, source, suffix) =>
					`${prefix}${safeImagePath(source) || source}${suffix}`,
			);
		}

		// Fallback if marked is missing
		const escapedText = escapeMessageHtml(safeText);
		return escapedText.replace(/\n/g, "<br>");
	} catch (_error) {
		const escapedText = escapeMessageHtml(safeText);
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
		if (Number.isNaN(dbDate.getTime())) {
			return timestamp;
		}
		let hours = dbDate.getHours();
		let minutes = dbDate.getMinutes();

		hours = hours < 10 ? `0${hours}` : hours;
		minutes = minutes < 10 ? `0${minutes}` : minutes;

		return `${hours}:${minutes}`;
	} catch (_error) {
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
