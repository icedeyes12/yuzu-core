/**
 * FILE: static/js/modules/fence-components.js
 * DESCRIPTION: Concrete fence-block handlers: default code, mermaid, html.
 *
 * Each handler implements { strategy, buildHTML, activate }.
 * All components:
 *   - preserve raw source (stored in data-fence-source)
 *   - expose a Copy button
 *   - expose an Inspect toggle where applicable
 */

import {
	registerFenceHandler,
	escAttr,
} from "./fence-registry.js";

// ── Copy helper (shared) ─────────────────────────────────────────────────────

function copyToClipboard(text) {
	void navigator.clipboard?.writeText(text).catch(() => {});
}

// ── Icon helpers (inline SVGs, no emoji, Lucide-style) ───────────────────────

function iconCopy() {
	return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
}

function iconInspect() {
	return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
}

// ── Common header builder ─────────────────────────────────────────────────────

/**
 * Build a standard block header HTML string.
 *
 * @param {string} label        — left-side text (language badge)
 * @param {string[]} actions    — array of action button HTML strings
 * @returns {string}
 */
function buildHeader(label, actions = []) {
	const actionsHtml = actions.join("");
	return `<div class="fence-header">
  <span class="fence-lang-badge">${escAttr(label)}</span>
  <div class="fence-actions">${actionsHtml}</div>
</div>`;
}

function buildCopyBtn() {
	return `<button class="fence-action-btn fence-copy-btn" title="Copy" type="button">${iconCopy()} Copy</button>`;
}

function buildInspectBtn() {
	return `<button class="fence-action-btn fence-inspect-btn" title="Toggle source" type="button">${iconInspect()} Inspect</button>`;
}

// ── Default code block handler ────────────────────────────────────────────────

/**
 * Default handler: immediate rendering with hljs.
 * Wraps the standard <pre><code> in a styled container with a header.
 */
const defaultCodeHandler = {
	strategy: "immediate",

	buildHTML(source, lang) {
		const header = buildHeader(lang || "code", [buildCopyBtn()]);
		const escapedSource = escAttr(source);
		const langClass = lang ? ` class="language-${escAttr(lang)}"` : "";
		return `<div class="fence-block fence-block--code" data-fence-lang="${escAttr(lang)}" data-fence-source="${escapedSource}">
  ${header}
  <pre><code${langClass}>${escapedSource}</code></pre>
</div>`;
	},

	activate(el, _source) {
		// Copy button
		el.querySelector(".fence-copy-btn")?.addEventListener("click", () => {
			const raw = el.dataset.fenceSource || "";
			copyToClipboard(raw);
			const btn = el.querySelector(".fence-copy-btn");
			if (btn) {
				btn.textContent = "Copied!";
				setTimeout(() => {
					btn.innerHTML = `${iconCopy()} Copy`;
				}, 1200);
			}
		});

		// hljs highlight
		const codeEl = el.querySelector("pre code");
		if (codeEl && window.hljs && !codeEl.classList.contains("hljs")) {
			window.hljs.highlightElement(codeEl);
		}
	},
};

registerFenceHandler("__default__", defaultCodeHandler);

// ── Mermaid handler ───────────────────────────────────────────────────────────

const mermaidHandler = {
	strategy: "buffered",

	buildHTML(source, _lang) {
		const header = buildHeader("Mermaid", [buildInspectBtn(), buildCopyBtn()]);
		return `<div class="fence-block fence-block--mermaid" data-fence-lang="mermaid" data-fence-source="${escAttr(source)}">
  ${header}
  <div class="fence-mermaid-body">
    <div class="fence-mermaid-diagram" data-view="diagram"></div>
    <div class="fence-mermaid-source" data-view="source" hidden>${defaultCodeHandler.buildHTML(source, "mermaid").replace('data-fence-lang="mermaid"', 'data-fence-lang="mermaid" data-fence-inert="1"')}</div>
  </div>
</div>`;
	},

	activate(el, source) {
		const diagramEl = el.querySelector(".fence-mermaid-diagram");
		const sourceEl = el.querySelector(".fence-mermaid-source");
		const inspectBtn = el.querySelector(".fence-inspect-btn");
		let showingSource = false;

		// Inspect toggle: visibility only, never re-renders diagram
		inspectBtn?.addEventListener("click", () => {
			showingSource = !showingSource;
			if (diagramEl) diagramEl.hidden = showingSource;
			if (sourceEl) sourceEl.hidden = !showingSource;
			inspectBtn.classList.toggle("fence-action-btn--active", showingSource);

			// Activate inspect code block on first toggle if needed
			if (showingSource && sourceEl) {
				const innerFence = sourceEl.querySelector("[data-fence-lang]");
				if (innerFence && !innerFence.dataset.fenceActivated) {
					innerFence.dataset.fenceActivated = "1";
					defaultCodeHandler.activate(innerFence, source);
				}
			}
		});

		// Copy button
		el.querySelector(".fence-copy-btn")?.addEventListener("click", () => {
			copyToClipboard(el.dataset.fenceSource || source);
			const btn = el.querySelector(".fence-copy-btn");
			if (btn) {
				btn.textContent = "Copied!";
				setTimeout(() => {
					btn.innerHTML = `${iconCopy()} Copy`;
				}, 1200);
			}
		});

		// Async Mermaid rendering
		if (!window.mermaid || !diagramEl) return;

		// Global Mermaid initialization check
		if (!window._mermaidInitialized) {
			try {
				window.mermaid.initialize({
					startOnLoad: false,
					securityLevel: "loose",
					theme: "dark",
				});
				window._mermaidInitialized = true;
			} catch (_e) {
				// ignore if initialized
			}
		}

		const svgId = `mermaid-svg-${Math.random().toString(36).slice(2, 9)}`;

		if (typeof window.mermaid.render === "function") {
			window.mermaid
				.render(svgId, source)
				.then(({ svg }) => {
					if (diagramEl) diagramEl.innerHTML = svg;
				})
				.catch((err) => {
					console.warn("Mermaid rendering failed:", err);
					if (diagramEl) {
						diagramEl.innerHTML = `<pre class="mermaid-fallback"><code>${escAttr(source)}</code></pre>`;
					}
				});
		} else if (typeof window.mermaid.init === "function") {
			diagramEl.id = svgId;
			diagramEl.textContent = source;
			diagramEl.className = "fence-mermaid-diagram mermaid";
			try {
				window.mermaid.init(undefined, diagramEl);
			} catch (_err) {
				diagramEl.textContent = source;
			}
		}
	},
};

registerFenceHandler("mermaid", mermaidHandler);

// ── HTML preview handler ──────────────────────────────────────────────────────

// Global window message listener for sandboxed iframe height auto-resizing
if (typeof window !== "undefined" && !window._htmlResizeListenerInstalled) {
	window._htmlResizeListenerInstalled = true;
	window.addEventListener("message", (event) => {
		if (event.data?.type === "yuzu-html-resize" && event.data?.height) {
			const iframes = document.querySelectorAll(".fence-html-iframe");
			for (const iframe of iframes) {
				if (iframe.contentWindow === event.source) {
					const targetH = Math.max(350, Math.ceil(event.data.height) + 24);
					iframe.style.height = `${targetH}px`;
					break;
				}
			}
		}
	});
}

const htmlPreviewHandler = {
	strategy: "buffered",

	buildHTML(source, _lang) {
		const previewBtn = `<button class="fence-action-btn fence-preview-btn fence-action-btn--active" title="Show rendered preview" type="button">Preview</button>`;
		const rawBtn = `<button class="fence-action-btn fence-rawcode-btn" title="Show raw HTML source" type="button">Raw Code</button>`;
		const header = buildHeader("HTML Preview", [previewBtn, rawBtn, buildCopyBtn()]);

		const inspectBlock = defaultCodeHandler.buildHTML(source, "html")
			.replace('data-fence-lang="html"', 'data-fence-lang="html" data-fence-inert="1"');

		// Script injected inside srcdoc to send height to parent window postMessage listener
		const resizeHelperScript = `<script>(function(){function s(){var h=Math.max(document.documentElement?document.documentElement.scrollHeight:0,document.body?document.body.scrollHeight:0);if(h>0){window.parent.postMessage({type:'yuzu-html-resize',height:h},'*');}}window.addEventListener('load',s);if(typeof ResizeObserver!=='undefined'&&document.body){new ResizeObserver(s).observe(document.body);}setTimeout(s,200);setTimeout(s,600);})();</script>`;

		const srcdocContent = source + resizeHelperScript;

		return `<div class="fence-block fence-block--html-preview" data-fence-lang="html" data-fence-source="${escAttr(source)}">
  ${header}
  <div class="fence-html-body">
    <iframe class="fence-html-iframe" sandbox="allow-scripts allow-forms allow-popups allow-modals" srcdoc="${escAttr(srcdocContent)}" title="HTML Preview"></iframe>
    <div class="fence-html-source-block" hidden>${inspectBlock}</div>
  </div>
</div>`;
	},

	activate(el, source) {
		const iframe = el.querySelector(".fence-html-iframe");
		const sourceBlock = el.querySelector(".fence-html-source-block");
		const previewBtn = el.querySelector(".fence-preview-btn");
		const rawBtn = el.querySelector(".fence-rawcode-btn");

		// Activate inner inspect code block once on load
		if (sourceBlock) {
			const innerFenceEl = sourceBlock.querySelector("[data-fence-lang]");
			if (innerFenceEl && !innerFenceEl.dataset.fenceActivated) {
				innerFenceEl.dataset.fenceActivated = "1";
				defaultCodeHandler.activate(innerFenceEl, source);
			}
		}

		// Toggle: Preview ⇄ Raw Code — visibility only, no re-render
		let showingPreview = true;

		function setView(preview) {
			showingPreview = preview;
			if (iframe) iframe.hidden = !preview;
			if (sourceBlock) sourceBlock.hidden = preview;
			previewBtn?.classList.toggle("fence-action-btn--active", preview);
			rawBtn?.classList.toggle("fence-action-btn--active", !preview);
		}

		previewBtn?.addEventListener("click", () => setView(true));
		rawBtn?.addEventListener("click", () => setView(false));

		// Copy always uses raw source
		el.querySelector(".fence-copy-btn")?.addEventListener("click", () => {
			copyToClipboard(el.dataset.fenceSource || source);
			const btn = el.querySelector(".fence-copy-btn");
			if (btn) {
				btn.textContent = "Copied!";
				setTimeout(() => { btn.innerHTML = `${iconCopy()} Copy`; }, 1200);
			}
		});
	},
};

registerFenceHandler("html", htmlPreviewHandler);
