/* Badge labels and presentation data. Ported from static/js/badge-registry.js. */

import { escapeHtml } from "./tool-renderer/dom-utils.js";

const badgeLabels = Object.freeze({
	official: "Official",
	community: "Community",
	custom: "Custom",
	experimental: "Experimental",
	deprecated: "Deprecated",
	preview: "Preview",
	unknown: "Unknown",
});

export function getLabel(badge) {
	return badgeLabels[badge] || badgeLabels.unknown;
}

export function render(provider) {
	const identity = provider;
	if (!identity) return "";
	return `<span class="provider-identity-badge provider-identity-badge--${escapeHtml(identity.badge)}">${getLabel(identity.badge)}</span>`;
}

export const BadgeRegistry = Object.freeze({ badgeLabels, getLabel, render });
