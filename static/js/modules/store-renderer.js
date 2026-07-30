import { createMessageElement } from "./messages.js";
import { chatStore } from "./store.js";
import "./fence-components.js";
import { patchContentContainer } from "./renderer/dom-patcher.js";
import {
	activateMessageFences,
	cancelMessageFenceWork,
	cleanupMessageFences,
} from "./renderer/fence-lifecycle.js";
import {
	installMarkedFenceRenderer,
	renderMessageHTML,
} from "./renderer/markdown-parser.js";
import {
	isNearBottom,
	scrollToBottom,
	shouldFollowBottom,
} from "./renderer/scroll-manager.js";

installMarkedFenceRenderer();

export class DOMRenderer {
	constructor(containerId) {
		this.container = document.getElementById(containerId);
		this.renderedIds = new Set();
		this.activeTypingIndicator = null;
		this.activeError = null;
		this.pendingRender = null;
		this.renderFrame = null;
		this.renderFrameCancel = null;
		this.lastRenderedMessageHashes = new Map();
		this.unsubscribe = chatStore.subscribe((...args) =>
			this.scheduleRender(...args),
		);
	}

	scheduleRender(messages, isGenerating, error = null) {
		this.pendingRender = { messages, isGenerating, error };
		if (this.renderFrame !== null) return;
		if (typeof requestAnimationFrame === "function") {
			this.renderFrameCancel = cancelAnimationFrame;
			this.renderFrame = requestAnimationFrame(() => {
				this.renderFrame = null;
				this.renderFrameCancel = null;
				this._renderPending();
			});
		} else {
			this.renderFrameCancel = clearTimeout;
			this.renderFrame = setTimeout(() => {
				this.renderFrame = null;
				this.renderFrameCancel = null;
				this._renderPending();
			}, 16);
		}
	}

	_renderPending() {
		const pending = this.pendingRender;
		this.pendingRender = null;
		if (pending)
			this.render(pending.messages, pending.isGenerating, pending.error);
	}

	flushPendingRender() {
		if (this.renderFrame !== null) {
			this.renderFrameCancel?.(this.renderFrame);
			this.renderFrame = null;
			this.renderFrameCancel = null;
		}
		this._renderPending();
	}

	cancelPendingRender() {
		if (this.renderFrame !== null) {
			this.renderFrameCancel?.(this.renderFrame);
			this.renderFrame = null;
			this.renderFrameCancel = null;
		}
		this.pendingRender = null;
	}

	dispose() {
		this.unsubscribe?.();
		this.unsubscribe = null;
		this.cancelPendingRender();
		cancelMessageFenceWork();
		cleanupMessageFences(this.container);
		this.lastRenderedMessageHashes.clear();
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
				this._updateMessageDOM(el, msg);
				this.renderedIds.add(msg.id);
				if (shouldFollowBottom(this.container)) scrollToBottom();
			} else {
				this._updateMessageDOM(el, msg);
				if (
					msg.role === "assistant" &&
					!msg.metadata?.isFrozen &&
					isNearBottom(this.container)
				)
					scrollToBottom();
			}
		}
		for (const oldId of this.renderedIds) {
			if (!newRenderedIds.has(oldId)) {
				const oldElement = this.container.querySelector(
					`[data-message-id="${oldId}"]`,
				);
				if (oldElement) cleanupMessageFences(oldElement);
				oldElement?.remove();
				this.renderedIds.delete(oldId);
				this.lastRenderedMessageHashes.delete(oldId);
			}
		}
		this._syncTypingIndicator(messages, isGenerating);
		this._syncError(error);
		for (const message of messages) {
			if (message.role !== "assistant") continue;
			const messageElement = this.container.querySelector(
				`[data-message-id="${message.id}"]`,
			);
			activateMessageFences(messageElement, message, isGenerating);
		}
	}

	_createMessageDOM(msg) {
		const el = createMessageElement(msg.role, msg.content, msg.timestamp);
		el.setAttribute("data-message-id", msg.id);
		return el;
	}

	_updateMessageDOM(el, msg) {
		const contentContainer = el.querySelector(".message-content");
		if (!contentContainer) return;
		const messageHash = JSON.stringify([
			msg.content || "",
			msg.metadata?.isFrozen ?? false,
			msg.toolCalls || [],
			msg.attachments || [],
			msg.toolResponse || null,
		]);
		if (this.lastRenderedMessageHashes.get(msg.id) === messageHash) return;
		this.lastRenderedMessageHashes.set(msg.id, messageHash);
		let html = renderMessageHTML(msg);
		if (msg.attachments?.length) {
			html += `<div class="attachments">${msg.attachments.map((att) => this._renderAttachment(att)).join("")}</div>`;
		}
		if (msg.toolCalls?.length)
			html += `<div class="tools-container">${msg.toolCalls.map((tc) => this._renderToolCall(tc)).join("")}</div>`;
		patchContentContainer(contentContainer, html);
		this._enhanceContent(contentContainer);
		el.querySelector(".copy-message-btn")?.setAttribute(
			"data-message-content",
			msg.content || "",
		);
	}

	_renderAttachment(att) {
		let url = att.url || att.path;
		if (!url) return "";
		if (att.path && !att.url) {
			const normalizedPath = att.path.replace(/\\/g, "/");
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
	}

	_renderToolCall(tc) {
		const completed = tc.status === "completed";
		const failed = tc.status === "error";
		const statusIcon = completed ? "✓" : failed ? "!" : "…";
		const name = tc.name || tc?.function?.name || "tool";
		const state = completed ? "done" : failed ? "failed" : "working";
		const args = tc.arguments
			? `<pre><code>${escapeHtml(tc.arguments)}</code></pre>`
			: "Waiting for result...";
		if (completed)
			return `<span class="tool-call-summary tool-call-summary--done"><span aria-hidden="true">${statusIcon}</span><span>${escapeHtml(name)}</span></span>`;
		return `<details class="tool-call-block tool-call-block--${state}" open><summary class="tool-header"><span aria-hidden="true">${statusIcon}</span><span>Calling ${escapeHtml(name)}</span></summary><div class="tool-body">${args}</div></details>`;
	}

	_enhanceContent(contentContainer) {
		if (window.hljs)
			contentContainer.querySelectorAll("pre code").forEach((block) => {
				if (
					!block.closest("[data-fence-lang]") &&
					!block.classList.contains("hljs")
				)
					window.hljs.highlightElement(block);
			});
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
