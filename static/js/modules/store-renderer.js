import { createMessageElement, renderMessageContent } from "./messages.js";
import { scrollToBottom } from "./scroll.js";
import { chatStore } from "./store.js";
import { renderToolResultEvent } from "./tool-renderer/index.js";

/**
 * The DOMRenderer acts strictly as a subscriber to ConversationStore.
 * It linearly renders the array of messages to the DOM and does not read from it.
 */
export class DOMRenderer {
	constructor(containerId) {
		this.container = document.getElementById(containerId);
		this.renderedIds = new Set();
		this.activeTypingIndicator = null;
		this.activeError = null;

		// Subscribe to store updates
		chatStore.subscribe(this.render.bind(this));
	}

	render(messages, isGenerating, error = null) {
		if (!this.container) return;

		const newRenderedIds = new Set();

		for (const msg of messages) {
			newRenderedIds.add(msg.id);

			let el = this.container.querySelector(`[data-message-id="${msg.id}"]`);

			if (!el) {
				el = this._createMessageDOM(msg);
				this.container.appendChild(el);
				this.renderedIds.add(msg.id);
				scrollToBottom();
			} else {
				this._updateMessageDOM(el, msg);
				if (msg.role === "assistant" && !msg.metadata.isFrozen)
					scrollToBottom();
			}
		}

		// Remove orphaned DOM elements (messages no longer in store)
		for (const oldId of this.renderedIds) {
			if (!newRenderedIds.has(oldId)) {
				this.container.querySelector(`[data-message-id="${oldId}"]`)?.remove();
				this.renderedIds.delete(oldId);
			}
		}

		// Handle typing indicator via the `isGenerating` flag and message states
		this._syncTypingIndicator(messages, isGenerating);
		this._syncError(error);
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

		let html;

		// 1. Base Content rendering based on role
		if (msg.role === "tool") {
			try {
				const toolEvent = JSON.parse(msg.content);
				html = renderToolResultEvent({
					...toolEvent,
					name: msg.toolResponse?.name || toolEvent.name,
					call_id: msg.toolResponse?.callId || toolEvent.call_id,
				});
			} catch (_error) {
				html = renderToolResultEvent({
					name: msg.toolResponse?.name || "unknown",
					ok: false,
					data: { raw: msg.content },
				});
			}
		} else {
			html = renderMessageContent(msg.content, msg.role === "user");
		}

		// 2. Attachments
		if (msg.attachments?.length) {
			const attachmentsHtml = msg.attachments
				.map((att) => {
					let url = att.url || att.path;
					if (!url) return "";
					if (att.path && !att.url) {
						const normalizedPath = att.path.replace(/\\\\/g, "/");
						const filename = normalizedPath.split("/").pop();
						if (!filename || filename.includes("..")) return "";
						const directory = normalizedPath.includes("generated_images")
							? "generated_images"
							: normalizedPath.includes("uploads")
								? "uploads"
								: null;
						if (!directory) return "";
						url = `/api/static/${directory}/${encodeURIComponent(filename)}`;
					}
					return `<img src="${escapeHtml(url)}" class="attachment-img" alt="Attachment" />`;
				})
				.join("");
			html += `<div class="attachments">${attachmentsHtml}</div>`;
		}

		// 3. Tool Calls (For Assistant messages)
		if (msg.toolCalls?.length) {
			const toolsHtml = msg.toolCalls
				.map((tc) => {
					const completed = tc.status === "completed";
					const failed = tc.status === "error";
					const statusIcon = completed ? "✓" : failed ? "!" : "…";
					const name = tc.name || tc?.function?.name || "tool";
					const state = completed ? "done" : failed ? "failed" : "working";
					const args = tc.arguments
						? `<pre><code>${escapeHtml(tc.arguments)}</code></pre>`
						: "Waiting for result...";

					if (completed) {
						return `<span class="tool-call-summary tool-call-summary--done"><span aria-hidden="true">${statusIcon}</span><span>${escapeHtml(name)}</span></span>`;
					}
					return `<details class="tool-call-block tool-call-block--${state}" open><summary class="tool-header"><span aria-hidden="true">${statusIcon}</span><span>Calling ${escapeHtml(name)}</span></summary><div class="tool-body">${args}</div></details>`;
				})
				.join("");
			html += `<div class="tools-container">${toolsHtml}</div>`;
		}

		if (contentContainer.getAttribute("data-last-hash") !== html) {
			contentContainer.innerHTML = html;
			contentContainer.setAttribute("data-last-hash", html);
			this._enhanceContent(contentContainer);
		}
		const copyButton = el.querySelector(".copy-message-btn");
		if (copyButton) {
			copyButton.setAttribute("data-message-content", msg.content || "");
		}
	}

	_enhanceContent(contentContainer) {
		if (window.hljs) {
			contentContainer.querySelectorAll("pre code").forEach((block) => {
				if (block.classList.contains("language-mermaid") && window.mermaid) {
					const pre = block.parentElement;
					const div = document.createElement("div");
					div.className = "mermaid";
					div.textContent = block.textContent;
					pre.parentNode.replaceChild(div, pre);
					try {
						window.mermaid.init(undefined, div);
					} catch (_error) {
						return;
					}
					return;
				}
				if (!block.classList.contains("hljs"))
					window.hljs.highlightElement(block);
			});
		}
		if (window.renderMathInElement) {
			try {
				window.renderMathInElement(contentContainer, {
					delimiters: [
						{ left: "$$", right: "$$", display: true },
						{ left: "\\[", right: "\\]", display: true },
						{ left: "$", right: "$", display: false },
						{ left: "\\(", right: "\\)", display: false },
					],
					throwOnError: false,
				});
			} catch (_error) {
				return;
			}
		}
	}

	_syncTypingIndicator(messages, isGenerating) {
		const lastMsg = messages[messages.length - 1];

		// If generating and last message is NOT an assistant message (e.g. user just hit enter)
		// Or if it's an assistant message but hasn't received content/tools yet
		const needsIndicator = Boolean(
			isGenerating &&
				lastMsg?.role === "assistant" &&
				!lastMsg.content &&
				!(lastMsg.toolCalls || []).length,
		);

		if (needsIndicator && !this.activeTypingIndicator) {
			this.activeTypingIndicator = document.createElement("div");
			this.activeTypingIndicator.className = "typing-indicator";
			this.activeTypingIndicator.innerHTML =
				"<span></span><span></span><span></span>";
			this.container.appendChild(this.activeTypingIndicator);
			scrollToBottom();
		} else if (!needsIndicator && this.activeTypingIndicator) {
			this.activeTypingIndicator.remove();
			this.activeTypingIndicator = null;
		}
	}

	_syncError(error) {
		if (!error) {
			this.activeError?.remove();
			this.activeError = null;
			return;
		}
		if (!this.activeError) {
			this.activeError = document.createElement("div");
			this.activeError.className = "chat-runtime-error";
			this.activeError.setAttribute("role", "alert");
			this.container.appendChild(this.activeError);
		}
		this.activeError.textContent = error;
	}
}

function escapeHtml(value) {
	return String(value ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

export const domRenderer = new DOMRenderer("chatContainer");
