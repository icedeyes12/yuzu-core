/**
 * FILE: static/js/modules/fence-registry.js
 * DESCRIPTION: Pluggable fenced-code-block component registry.
 *
 * Architecture:
 *   - Two render strategies:
 *       "immediate"  — code is syntax-highlighted on every token update (normal code).
 *       "buffered"   — block is held invisible until the closing fence arrives,
 *                      then rendered once. Never shows partial-parse errors.
 *   - Block components are registered per language.  Unregistered languages
 *     fall back to the default "code" handler.
 *   - marked.js custom renderer calls `buildFenceHTML()` during markdown parsing.
 *     Post-parse, `activateFenceBlocks()` mounts interactive components.
 */

/** @typedef {"immediate"|"buffered"} RenderStrategy */

/**
 * @typedef {Object} FenceHandler
 * @property {RenderStrategy} strategy
 * @property {(source: string, lang: string) => string} buildHTML
 *   Returns the *outer* HTML for the block (header + placeholder body).
 *   Called during markdown parsing — must be synchronous and return a string.
 * @property {(el: HTMLElement, source: string) => void} activate
 *   Called once the element is in the DOM (after innerHTML is set).
 *   For buffered components this fires only after the closing fence arrives.
 */

const _registry = new Map(); // lang → FenceHandler

/**
 * Register a fenced-block handler for one or more language strings.
 *
 * @param {string|string[]} langs
 * @param {FenceHandler} handler
 */
export function registerFenceHandler(langs, handler) {
	for (const lang of [langs].flat()) {
		_registry.set(lang.toLowerCase(), handler);
	}
}

/**
 * Resolve the handler for `lang`.  Falls back to the "code" default.
 *
 * @param {string} lang
 * @returns {FenceHandler}
 */
export function resolveFenceHandler(lang) {
	return _registry.get((lang || "").toLowerCase()) || _registry.get("__default__");
}

/**
 * Build the HTML string for a fenced block.
 * Called from the marked custom renderer — runs during markdown parsing.
 *
 * For "buffered" blocks that are still streaming (closingFenceReceived=false),
 * we emit a "pending" placeholder that `activateFenceBlocks` will skip.
 *
 * @param {string} lang
 * @param {string} source  — raw code content (may be partial during stream)
 * @param {boolean} isComplete  — true once the closing fence ``` has been seen
 * @returns {string}
 */
export function buildFenceHTML(lang, source, isComplete = true) {
	const handler = resolveFenceHandler(lang);

	if (handler.strategy === "buffered" && !isComplete) {
		// Return a silent placeholder.  No error, no content.
		return `<div class="fence-block fence-block--pending" data-fence-lang="${escAttr(lang)}" data-fence-source="${escAttr(source)}" data-fence-strategy="buffered"></div>`;
	}

	return handler.buildHTML(source, lang);
}

/**
 * Mount all fence components found inside `root`.
 * Call this after `contentContainer.innerHTML = html`.
 *
 * @param {HTMLElement} root
 */
export function activateFenceBlocks(root) {
	for (const el of root.querySelectorAll("[data-fence-lang]")) {
		// Pending (stream still open) — skip
		if (el.classList.contains("fence-block--pending")) continue;
		// Already activated
		if (el.dataset.fenceActivated) continue;

		el.dataset.fenceActivated = "1";
		const lang = el.dataset.fenceLang || "";
		const source = el.dataset.fenceSource || el.dataset.fenceRawsource || "";
		const handler = resolveFenceHandler(lang);
		try {
			handler.activate(el, source);
		} catch (_err) {
			// Activation failures are silent — the raw source is preserved
		}
	}
}

/**
 * Mark all pending (buffered, incomplete) fence blocks inside `root` as complete
 * and activate them.  Called when the stream closes.
 *
 * @param {HTMLElement} root
 */
export function flushPendingFenceBlocks(root) {
	for (const el of root.querySelectorAll(".fence-block--pending")) {
		const lang = el.dataset.fenceLang || "";
		const source = el.dataset.fenceSource || "";
		const handler = resolveFenceHandler(lang);

		// Replace placeholder with the real component HTML
		const tmp = document.createElement("div");
		tmp.innerHTML = handler.buildHTML(source, lang);
		const real = tmp.firstElementChild;
		if (!real) continue;

		el.replaceWith(real);

		real.dataset.fenceActivated = "1";
		try {
			handler.activate(real, source);
		} catch (_err) {
			// silent
		}
	}
}

// ── helpers ──────────────────────────────────────────────────────────────────

function escAttr(str) {
	return String(str ?? "")
		.replace(/&/g, "&amp;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;");
}

export { escAttr };
