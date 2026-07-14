import { chatStore } from "./store.js";
import { createMessageElement } from "./messages.js";
import { scrollToBottom } from "./scroll.js";

/**
 * The DOMRenderer acts strictly as a subscriber to ConversationStore.
 * It linearly renders the array of messages to the DOM and does not read from it.
 */
import { ToolRenderers } from "./tool-renderers.js";

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

		let html;
		
		// 1. Base Content rendering based on role
		if (msg.role === "tool") {
			try {
				const toolData = typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
				const toolName = msg.name || "default";
				const rendererFn = ToolRenderers[toolName] || ToolRenderers.default;
				html = rendererFn(toolData);
			} catch (e) {
				console.error(`Failed to parse tool content for ${msg.name}:`, e);
				const rendererFn = ToolRenderers.error || ToolRenderers.default;
				html = rendererFn(`Error parsing tool data: ${e.message}`);
			}
		} else {
			html = window.renderMessageContent ? window.renderMessageContent(msg.content, msg.role === "user") : msg.content;
		}
		
		// 2. Attachments
		if (msg.attachments && msg.attachments.length > 0) {
			const attachmentsHtml = msg.attachments.map(att => {
				let url = att.url || att.path;
				if (!url) return "";
				// Fix relative pathing issue (/chat/static/... 404 error)
				if (url.startsWith("static/")) {
					url = "/" + url;
				} else if (url.startsWith("generated_images/")) {
					url = "/static/" + url;
				}
				if (att.path && !url.startsWith("/api/media") && !url.startsWith("/static/")) {
					url = `/api/media?path=${encodeURIComponent(att.path)}`;
				}
				return `<img src="${url}" class="attachment-img" />`;
			}).join("");
			html += `<div class="attachments">${attachmentsHtml}</div>`;
		}

		// 3. Tool Calls (For Assistant messages)
		if (msg.tool_calls && msg.tool_calls.length > 0) {
			const toolsHtml = msg.tool_calls.map(tc => {
				const statusIcon = tc.status === "completed" ? "✓" : (tc.status === "error" ? "❌" : "⚙️");
				const name = tc.name || tc?.function?.name || "tool";
				const args = tc.arguments ? `<pre><code>${tc.arguments}</code></pre>` : "Waiting for result...";
				
				// Hide internal or completed tool calls in a details block so they don't leak into the main reading flow
				return `<details class="tool-call-block" ${tc.status !== "completed" ? "open" : ""}>
					<summary class="tool-header">${statusIcon} Calling ${name}</summary>
					<div class="tool-body">${args}</div>
				</details>`;
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
					// Handle Mermaid diagrams specially
					if (block.classList.contains("language-mermaid")) {
						if (window.mermaid) {
							// Move it to a div for mermaid to render
							const pre = block.parentElement;
							const div = document.createElement("div");
							div.className = "mermaid";
							div.textContent = block.textContent;
							pre.parentNode.replaceChild(div, pre);
							
							try {
								mermaid.init(undefined, div);
							} catch(e) {
								console.error("Mermaid error:", e);
							}
						}
						return;
					}
					
					if (!block.classList.contains("hljs")) hljs.highlightElement(block);
				});
			}

			// LaTeX Math rendering
			if (window.renderMathInElement) {
				try {
					window.renderMathInElement(contentContainer, {
						delimiters: [
							{ left: "$$", right: "$$", display: true },
							{ left: "\\[", right: "\\]", display: true },
							{ left: "$", right: "$", display: false },
							{ left: "\\(", right: "\\)", display: false }
						],
						throwOnError: false
					});
				} catch (e) {
					console.error("KaTeX render error:", e);
				}
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
