// FILE: static/js/modules/tool-renderer/cards/generic.js
// DESCRIPTION: Generic card for tools without a specialised renderer.
// Renders structured `fields` directly. Replaces the old accordion.

import { escapeHtml } from "../dom-utils.js";

function renderGenericCard(toolName, normalised, normalisedData) {
	const rows = Object.entries(normalisedData)
		.filter(([key]) => key !== "ok" && key !== "error_message")
		.map(([key, value]) => {
			let display;
			try {
				display =
					typeof value === "string" ? value : JSON.stringify(value, null, 2);
			} catch (_e) {
				display = String(value);
			}
			return [
				`<div class="generic-card__row">`,
				`<div class="generic-card__key">${escapeHtml(key)}</div>`,
				`<pre class="generic-card__value">${escapeHtml(display)}</pre>`,
				`</div>`,
			].join("");
		})
		.join("");

	const status = normalised.ok
		? ""
		: `<div class="generic-card__error">${escapeHtml(
				normalised.error_message || "Tool error",
			)}</div>`;

	return [
		`<div class="tool-card tool-card--generic">`,
		`<div class="generic-card">`,
		`<div class="generic-card__header">`,
		`<span class="generic-card__icon" aria-hidden="true"><span class="visual-icon visual-icon--tool">◆</span></span>`,
		`<span class="generic-card__title">${escapeHtml(toolName)}</span>`,
		`</div>`,
		status,
		rows || `<div class="generic-card__empty">No payload.</div>`,
		`</div>`,
		`</div>`,
	].join("");
}

export { renderGenericCard };
