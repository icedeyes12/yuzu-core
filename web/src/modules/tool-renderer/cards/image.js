// FILE: static/js/modules/tool-renderer/cards/image.js
// DESCRIPTION: Image card for image_generate / image_edit.

import { renderRuntimeIcon } from "../../../runtime-icon-renderer.js";
import { escapeHtml, safeImagePath } from "../dom-utils.js";

function renderImageCard(normalised, _callId, { copyableContent = "" } = {}) {
	const { image_path, image_url, prompt, alt, model } = normalised;
	const path = safeImagePath(image_path || image_url);
	if (!path) {
		return renderImageError("Image path missing or unsafe.");
	}

	const altText = alt || "Tool-generated image";
	const promptText =
		copyableContent || (typeof prompt === "string" ? prompt.trim() : "");
	const promptMarkup = promptText
		? `<div class="image-card__prompt"><div class="image-card__prompt-toolbar"><span class="image-card__prompt-label">Prompt</span><button class="tool-card__copy image-card__copy" type="button" data-action="copy-tool-prompt" aria-label="Copy image prompt" title="Copy image prompt">${renderRuntimeIcon("copy", { size: 14, strokeWidth: 2 }) || ""}<span>Copy prompt</span></button></div><pre class="image-card__prompt-code"><code>${escapeHtml(promptText)}</code></pre></div>`
		: "";
	const modelLabel = model
		? `<div class="image-card__model">${escapeHtml(model)}</div>`
		: "";
	const mediaActions = `<div class="image-card__actions"><a class="tool-card__media-action" href="${escapeHtml(path)}" download aria-label="Download generated image" title="Download generated image">${renderRuntimeIcon("download", { size: 14, strokeWidth: 2 }) || ""}<span>Download</span></a><a class="tool-card__media-action" href="${escapeHtml(path)}" target="_blank" rel="noopener" aria-label="Open full image preview" title="Open full image preview">${renderRuntimeIcon("image", { size: 14, strokeWidth: 2 }) || ""}<span>Full preview</span></a></div>`;

	return [
		`<div class="tool-card tool-card--image">`,
		`<div class="image-card">`,
		promptMarkup,
		`<img class="image-card__img" src="${escapeHtml(path)}" alt="${escapeHtml(altText)}" loading="lazy" />`,
		mediaActions,
		modelLabel,
		`</div>`,
		`</div>`,
	].join("");
}

function renderImageError(message) {
	return [
		`<div class="tool-card tool-card--image">`,
		`<div class="image-card image-card--error">${escapeHtml(message)}</div>`,
		`</div>`,
	].join("");
}

export { renderImageCard };
