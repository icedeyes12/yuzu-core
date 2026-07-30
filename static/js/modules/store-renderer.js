import {
	activateFenceBlocks,
	buildFenceHTML,
	cleanupFenceBlocks,
	flushPendingFenceBlocks,
} from "./fence-registry.js";
import { createMessageElement, renderMessageContent } from "./messages.js";
import { isNearBottom, scrollToBottom, shouldFollowBottom } from "./scroll.js";
import { chatStore } from "./store.js";
import { renderToolResultEvent } from "./tool-renderer/index.js";
// Side-effect: registers mermaid, html, and default handlers
import "./fence-components.js";

// ── Custom marked renderer ─────────────────────────────────────────────────────
// Intercepts fenced code blocks and routes them through the fence registry.
// Installed once at module load.
(function _installMarkedFenceRenderer() {
	if (!window.marked) return; // marked not yet loaded — will be installed lazily
	_applyMarkedFenceRenderer();
	// Also hook if marked loads later (belt-and-suspenders for dynamic script load order)
})();

function _applyMarkedFenceRenderer() {
	if (!window.marked || window._fenceRendererInstalled) return;
	window._fenceRendererInstalled = true;

	const renderer = new window.marked.Renderer();

	renderer.code = (tokenOrCode, infostring, _escaped) => {
		// marked v5+ passes a token object; older versions pass (code, lang, escaped)
		let source, lang;
		if (
			tokenOrCode &&
			typeof tokenOrCode === "object" &&
			"text" in tokenOrCode
		) {
			source = tokenOrCode.text ?? "";
			lang = tokenOrCode.lang ?? "";
		} else {
			source = String(tokenOrCode ?? "");
			lang = infostring ?? "";
		}

		// During streaming the message hasn't "closed" yet, so we pass
		// isComplete=false for buffered blocks. The store-renderer patches
		// them to complete when the message is frozen.
		//
		// Limitation: marked sees the full content it was given at parse time.
		// "Incomplete" means the last fence token has no closing ``` yet, which
		// we detect by checking if the source text ends mid-block.  For simplicity
		// we pass isComplete=true here (marked only calls this renderer when it
		// has a complete token), and rely on the outer message-level freeze signal
		// to control buffered block visibility.
		return buildFenceHTML(lang, source, true);
	};

	window.marked.setOptions({
		breaks: true,
		gfm: true,
		sanitize: false,
		renderer,
	});
	window._markedConfigured = true;
}

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
		this.pendingRender = null;
		this.renderFrame = null;
		this.renderFrameCancel = null;
		this.lastRenderArgs = null;
		this.lastRenderedMessageHashes = new Map();

		// Subscribe to store updates
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
		if (pending) {
			this.render(pending.messages, pending.isGenerating, pending.error);
		}
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
		cleanupFenceBlocks(this.container);
		this.lastRenderedMessageHashes.clear();
	}

	render(messages, isGenerating, error = null) {
		if (!this.container) return;
		this.lastRenderArgs = { messages, isGenerating, error };

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
					!msg.metadata.isFrozen &&
					isNearBottom(this.container)
				) {
					scrollToBottom();
				}
			}
		}

		// Remove orphaned DOM elements (messages no longer in store)
		for (const oldId of this.renderedIds) {
			if (!newRenderedIds.has(oldId)) {
				const oldElement = this.container.querySelector(
					`[data-message-id="${oldId}"]`,
				);
				if (oldElement) cleanupFenceBlocks(oldElement);
				oldElement?.remove();
				this.renderedIds.delete(oldId);
				this.lastRenderedMessageHashes.delete(oldId);
			}
		}

		// Handle typing indicator via the `isGenerating` flag and message states
		this._syncTypingIndicator(messages, isGenerating);
		this._syncError(error);
		this._finalizeFenceBlocks(messages, isGenerating);
	}

	_createMessageDOM(msg) {
		// Use existing DOM element generator from messages.js
		// (We will refactor createMessageElement to accept the full msg object next)
		const el = createMessageElement(msg.role, msg.content, msg.timestamp);
		el.setAttribute("data-message-id", msg.id);

		// The caller appends the element before this method activates fence blocks.
		return el;
	}

	_finalizeFenceBlocks(messages, isGenerating) {
		if (!this.container?.isConnected) return;

		for (const message of messages) {
			if (message.role !== "assistant") continue;
			const messageElement = this.container.querySelector(
				`[data-message-id="${message.id}"]`,
			);
			const contentContainer =
				messageElement?.querySelector(".message-content");
			if (!contentContainer) continue;
			activateFenceBlocks(contentContainer);
			if (isGenerating || !message.metadata?.isFrozen) continue;
			flushPendingFenceBlocks(contentContainer);
			activateFenceBlocks(contentContainer);
		}
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
		if (this.lastRenderedMessageHashes.get(msg.id) === messageHash) {
			return;
		}
		this.lastRenderedMessageHashes.set(msg.id, messageHash);

		// Ensure marked renderer is installed (handles late script load order)
		_applyMarkedFenceRenderer();

		let html;
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

		if (msg.role === "assistant") {
			html = _classifyBufferedFences(html, msg.content);
		}

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

		this._patchContentContainer(contentContainer, html);
		this._enhanceContent(contentContainer);

		const copyButton = el.querySelector(".copy-message-btn");
		if (copyButton)
			copyButton.setAttribute("data-message-content", msg.content || "");
	}

	_patchContentContainer(root, html) {
		const desired = document.createElement("div");
		desired.innerHTML = html;
		_assignFenceKeys(root);
		_assignFenceKeys(desired);
		_patchChildren(root, desired);
	}

	_enhanceContent(contentContainer) {
		if (window.hljs) {
			contentContainer.querySelectorAll("pre code").forEach((block) => {
				// Skip fence-registry managed blocks (they handle their own activation)
				if (block.closest("[data-fence-lang]")) return;
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

/**
 * Classify buffered fences in rendered HTML against the raw markdown source.
 * Complete fences (opening + closing ``` both present) are left as-is so they
 * render immediately.  Incomplete fences (still streaming) are replaced with a
 * loading placeholder — hidden until the closing fence arrives.
 *
 * This runs on every store update tick. `flushPendingFenceBlocks` then
 * activates any placeholder whose fence became complete.
 *
 * @param {string} html        — rendered HTML from marked
 * @param {string} rawContent  — original raw markdown text
 * @returns {string}
 */
function _classifyBufferedFences(html, rawContent) {
	const BUFFERED_LANGS = ["mermaid", "html"];
	let result = html;
	const raw = rawContent || "";

	for (const lang of BUFFERED_LANGS) {
		if (!result.includes(`data-fence-lang="${lang}"`)) continue;

		const openRe = new RegExp(`^\`\`\`${lang}\\b`, "im");
		if (!openRe.test(raw)) continue;

		// Count standalone closing ``` lines that appear AFTER the opening fence
		const openMatch = openRe.exec(raw);
		const afterOpen = raw.slice(
			(openMatch?.index ?? 0) + (openMatch?.[0]?.length ?? 0),
		);
		const closeCount = afterOpen
			.split("\n")
			.filter((l) => l.trim() === "```").length;

		// If no closing fence yet — fence is still streaming — replace with placeholder
		if (closeCount === 0) {
			result = _replaceOuterDiv(
				result,
				`data-fence-lang="${lang}"`,
				`<div class="fence-block fence-block--pending" data-fence-lang="${lang}" data-fence-source="${escapeHtml(afterOpen)}" data-fence-strategy="buffered"></div>`,
			);
		}
		// closeCount > 0 → fence is complete → leave the rendered component in place
	}

	return result;
}

function _assignFenceKeys(root) {
	const counts = new Map();
	for (const el of root.querySelectorAll("[data-fence-lang]")) {
		const lang = el.dataset.fenceLang || "__unknown__";
		const index = (counts.get(lang) || 0) + 1;
		counts.set(lang, index);
		el.dataset.fenceKey = `${lang}:${index}`;
	}
}

function _patchChildren(currentParent, desiredParent) {
	const currentChildren = [...currentParent.childNodes];
	const keyedCurrent = new Map(
		currentChildren
			.filter((node) => node.nodeType === Node.ELEMENT_NODE)
			.map((node) => [node.dataset.fenceKey, node])
			.filter(([key]) => key),
	);
	const used = new Set();
	let cursor = currentParent.firstChild;

	for (const desiredNode of desiredParent.childNodes) {
		const key =
			desiredNode.nodeType === Node.ELEMENT_NODE
				? desiredNode.dataset.fenceKey
				: null;
		let currentNode = key ? keyedCurrent.get(key) : null;

		if (currentNode && !used.has(currentNode)) {
			if (currentNode !== cursor)
				currentParent.insertBefore(currentNode, cursor);
			used.add(currentNode);
			_patchNode(currentNode, desiredNode);
			cursor = currentNode.nextSibling;
			continue;
		}

		if (
			!key &&
			cursor &&
			!used.has(cursor) &&
			_sameNodeType(cursor, desiredNode)
		) {
			currentNode = cursor;
			used.add(currentNode);
			_patchNode(currentNode, desiredNode);
			cursor = currentNode.nextSibling;
			continue;
		}

		currentNode = desiredNode.cloneNode(true);
		currentParent.insertBefore(currentNode, cursor);
		used.add(currentNode);
		cursor = currentNode.nextSibling;
	}

	for (const node of [...currentParent.childNodes]) {
		if (used.has(node)) continue;
		cleanupFenceBlocks(node);
		node.remove();
	}
}

function _sameNodeType(current, desired) {
	if (current.nodeType !== desired.nodeType) return false;
	return (
		current.nodeType !== Node.ELEMENT_NODE ||
		current.nodeName === desired.nodeName
	);
}

function _patchNode(current, desired) {
	if (current.nodeType === Node.TEXT_NODE) {
		if (current.nodeValue !== desired.nodeValue)
			current.nodeValue = desired.nodeValue;
		return;
	}
	if (current.nodeType !== Node.ELEMENT_NODE) return;

	const isActivatedFence =
		current.matches("[data-fence-lang]") && current.dataset.fenceActivated;
	if (
		isActivatedFence &&
		current.dataset.fenceSource !== desired.dataset.fenceSource
	) {
		cleanupFenceBlocks(current);
		delete current.dataset.fenceActivated;
	}
	_patchNodeAttributes(current, desired);
	if (current.matches("[data-fence-lang]") && current.dataset.fenceActivated)
		return;
	_patchChildren(current, desired);
}

function _patchNodeAttributes(current, desired) {
	for (const name of [...current.attributes].map(
		(attribute) => attribute.name,
	)) {
		if (!desired.hasAttribute(name) && name !== "data-fence-activated") {
			current.removeAttribute(name);
		}
	}
	for (const attribute of desired.attributes) {
		if (attribute.name === "data-fence-activated") continue;
		if (current.getAttribute(attribute.name) !== attribute.value) {
			current.setAttribute(attribute.name, attribute.value);
		}
	}
}

/**
 * Replace the outer <div> containing `marker` in `html` with `replacement`.
 * Uses a depth counter to correctly match nested divs.
 *
 * @param {string} html
 * @param {string} marker   — attribute string to locate the target div
 * @param {string} replacement
 * @returns {string}
 */
function _replaceOuterDiv(html, marker, replacement) {
	const markerIdx = html.indexOf(marker);
	if (markerIdx === -1) return html;

	const divStart = html.lastIndexOf("<div", markerIdx);
	if (divStart === -1) return html;

	let depth = 0;
	let i = divStart;
	let divEnd = -1;
	while (i < html.length) {
		const nextOpen = html.indexOf("<div", i);
		const nextClose = html.indexOf("</div>", i);
		if (nextOpen !== -1 && nextOpen < nextClose) {
			depth++;
			i = nextOpen + 1;
		} else if (nextClose !== -1) {
			depth--;
			if (depth === 0) {
				divEnd = nextClose + 6;
				break;
			}
			i = nextClose + 1;
		} else {
			break;
		}
	}

	if (divEnd === -1) return html;
	return html.slice(0, divStart) + replacement + html.slice(divEnd);
}

export const domRenderer = new DOMRenderer("chatContainer");
