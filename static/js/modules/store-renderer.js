import { chatStore } from "./store.js";
import { createMessageElement } from "./messages.js";
import { scrollToBottom } from "./scroll.js";

/**
 * The DOMRenderer acts strictly as a subscriber to ConversationStore.
 * It linearly renders the array of messages to the DOM and does not read from it.
 */
export class DOMRenderer {
	constructor(containerId) {
		this.container = document.getElementById(containerId);
		this.renderedIds = new Set();
		this.activeTypingIndicator = null;
		
		// Subscribe to store updates
		chatStore.subscribe(this.render.bind(this));
	}

	render(messages, isGenerating) {
		if (!this.container) return;

		// If the store is empty, clear the DOM
		if (messages.length === 0) {
			this.container.innerHTML = "";
			this.renderedIds.clear();
			this.activeTypingIndicator = null;
			return;
		}

		// Fast path: map over messages and ensure they exist
		for (const msg of messages) {
			let el = this.container.querySelector(`[data-message-id="${msg.id}"]`);
			
			if (!el) {
				// Create new
				el = this._createMessageDOM(msg);
				this.container.appendChild(el);
				this.renderedIds.add(msg.id);
				scrollToBottom();
			} else {
				// Update existing IF NOT FROZEN
				if (msg.isFrozen) continue;
				this._updateMessageDOM(el, msg);
				if (msg.role === "assistant" && !msg.isFrozen) {
					// We only scroll on updates if we are the active generating element
					scrollToBottom();
				}
			}
		}

		// Handle typing indicator via the `isGenerating` flag and message states
		this._syncTypingIndicator(messages, isGenerating);
	}

	_createMessageDOM(msg) {
		// Use existing DOM element generator from messages.js
		// (We will refactor createMessageElement to accept the full msg object next)
		const el = createMessageElement(msg.role, msg.content, msg.timestamp);
		el.setAttribute("data-message-id", msg.id);
		
		// Render attachments and tool calls if any
		this._updateMessageDOM(el, msg);
		
		return el;
	}

	_updateMessageDOM(el, msg) {
		const contentContainer = el.querySelector(".message-content");
		if (!contentContainer) return;

		// 1. Base Content 
		let html = window.renderMessageContent ? window.renderMessageContent(msg.content, msg.role === "user") : msg.content;
		
		// 2. Attachments
		if (msg.attachments && msg.attachments.length > 0) {
			const attachmentsHtml = msg.attachments.map(att => {
				if (att.url) return `<img src="${att.url}" class="attachment-img" />`;
				if (att.path) return `<img src="/api/media?path=${encodeURIComponent(att.path)}" class="attachment-img" />`;
				return "";
			}).join("");
			html += `<div class="attachments">${attachmentsHtml}</div>`;
		}

		// 3. Tool Calls (For Assistant messages)
		if (msg.tool_calls && msg.tool_calls.length > 0) {
			const toolsHtml = msg.tool_calls.map(tc => {
				const statusIcon = tc.status === "completed" ? "✓" : (tc.status === "error" ? "❌" : "⚙️");
				const args = tc.arguments ? `<pre><code>${tc.arguments}</code></pre>` : "Waiting for result...";
				// We do NOT use <details> here intentionally to prevent state issues,
				// or if we do, we force them open/closed purely based on state, not DOM mutation.
				return `<div class="tool-call-block">
					<div class="tool-header">${statusIcon} Calling ${tc.name}</div>
					<div class="tool-body">${args}</div>
				</div>`;
			}).join("");
			html += `<div class="tools-container">${toolsHtml}</div>`;
		}
		
		// Only touch innerHTML if it has actually changed to avoid thrashing
		if (contentContainer.getAttribute("data-last-hash") !== html) {
			contentContainer.innerHTML = html;
			contentContainer.setAttribute("data-last-hash", html);
			
			// Syntax highlighting
			if (window.hljs) {
				contentContainer.querySelectorAll("pre code").forEach((block) => {
					if (!block.classList.contains("hljs")) hljs.highlightElement(block);
				});
			}
		}
	}

	_syncTypingIndicator(messages, isGenerating) {
		const lastMsg = messages[messages.length - 1];
		
		// If generating and last message is NOT an assistant message (e.g. user just hit enter)
		// Or if it's an assistant message but hasn't received content/tools yet
		const needsIndicator = isGenerating && 
			(lastMsg.role !== "assistant" || (lastMsg.role === "assistant" && !lastMsg.content && lastMsg.tool_calls.length === 0));

		if (needsIndicator && !this.activeTypingIndicator) {
			this.activeTypingIndicator = document.createElement("div");
			this.activeTypingIndicator.className = "typing-indicator";
			this.activeTypingIndicator.innerHTML = `<span></span><span></span><span></span>`;
			this.container.appendChild(this.activeTypingIndicator);
			scrollToBottom();
		} else if (!needsIndicator && this.activeTypingIndicator) {
			this.activeTypingIndicator.remove();
			this.activeTypingIndicator = null;
		}
	}
}

export const domRenderer = new DOMRenderer("chatContainer");
