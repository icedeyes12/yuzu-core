// FILE: static/js/modules/tool-renderer/cards/image.js
// DESCRIPTION: Image card for image_generate / image_edit.

import { escapeHtml, safeImagePath } from "../dom-utils.js";

function renderImageCard(normalised) {
	const { image_path, image_url, alt, model } = normalised;
	const path = safeImagePath(image_path || image_url);
	if (!path) {
		return renderImageError("Image path missing or unsafe.");
	}

	const altText = alt || "Tool-generated image";
	const modelLabel = model
		? `<div class="image-card__model">${escapeHtml(model)}</div>`
		: "";

	return [
		`<div class="tool-card tool-card--image">`,
		`<div class="image-card">`,
		`<img class="image-card__img" src="${escapeHtml(path)}" alt="${escapeHtml(altText)}" loading="lazy" />`,
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
