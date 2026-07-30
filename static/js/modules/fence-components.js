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
    <pre class="fence-mermaid-source" data-view="source" hidden><code>${escAttr(source)}</code></pre>
  </div>
</div>`;
	},

	activate(el, source) {
		const diagramEl = el.querySelector(".fence-mermaid-diagram");
		const sourceEl = el.querySelector(".fence-mermaid-source");
		let showingSource = false;

		// Inspect toggle
		el.querySelector(".fence-inspect-btn")?.addEventListener("click", () => {
			showingSource = !showingSource;
			diagramEl.hidden = showingSource;
			sourceEl.hidden = !showingSource;
			const btn = el.querySelector(".fence-inspect-btn");
			if (btn) {
				btn.classList.toggle("fence-action-btn--active", showingSource);
			}
		});

		// Copy
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

		// Render mermaid once
		if (!window.mermaid || !diagramEl) return;

		const id = `mermaid-${Math.random().toString(36).slice(2)}`;
		diagramEl.id = id;
		diagramEl.textContent = source;
		diagramEl.className = "fence-mermaid-diagram mermaid";

		try {
			// mermaid.run is the modern API (v10+); fall back to init for v9
			if (typeof window.mermaid.run === "function") {
				window.mermaid.run({ nodes: [diagramEl] }).catch(() => {
					diagramEl.textContent = source; // reset on error — don't show red errors
				});
			} else {
				window.mermaid.init(undefined, diagramEl);
			}
		} catch (_err) {
			// Silent — the source is available via Inspect
			diagramEl.textContent = source;
		}
	},
};

registerFenceHandler("mermaid", mermaidHandler);

// ── HTML preview handler ──────────────────────────────────────────────────────

const htmlPreviewHandler = {
	strategy: "buffered",

	buildHTML(source, _lang) {
		const header = buildHeader("HTML Preview", [buildInspectBtn(), buildCopyBtn()]);
		return `<div class="fence-block fence-block--html-preview" data-fence-lang="html" data-fence-source="${escAttr(source)}">
  ${header}
  <div class="fence-html-body">
    <iframe class="fence-html-iframe" sandbox="allow-scripts allow-forms allow-popups allow-modals" title="HTML Preview"></iframe>
    <pre class="fence-html-source" data-view="source" hidden><code>${escAttr(source)}</code></pre>
  </div>
</div>`;
	},

	activate(el, source) {
		const iframe = el.querySelector(".fence-html-iframe");
		const sourceEl = el.querySelector(".fence-html-source");
		let showingSource = false;

		// Write HTML into sandboxed iframe
		if (iframe) {
			const doc = iframe.contentDocument || iframe.contentWindow?.document;
			if (doc) {
				doc.open();
				doc.write(source);
				doc.close();

				// Auto-resize to content height
				iframe.onload = () => {
					try {
						const h = iframe.contentDocument?.body?.scrollHeight;
						if (h && h > 0) iframe.style.height = `${h + 32}px`;
					} catch (_err) {
						// cross-origin guard — leave default height
					}
				};
			}
		}

		// Inspect toggle
		el.querySelector(".fence-inspect-btn")?.addEventListener("click", () => {
			showingSource = !showingSource;
			if (iframe) iframe.hidden = showingSource;
			sourceEl.hidden = !showingSource;
			const btn = el.querySelector(".fence-inspect-btn");
			if (btn) btn.classList.toggle("fence-action-btn--active", showingSource);
		});

		// Copy
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
	},
};

registerFenceHandler("html", htmlPreviewHandler);
