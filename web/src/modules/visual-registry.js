/* Stable facade for presentation consumers; identity concerns live in focused
   registries. Ported from static/js/visual-registry.js. */

import { render as renderBadge } from "./badge-registry.js";
import {
	getProvider,
	listProviders,
	ProviderRegistry,
} from "./provider-registry.js";
import { escapeHtml } from "./tool-renderer/dom-utils.js";

export function renderLogo(provider, size = "default") {
	const identity = provider || ProviderRegistry.fallback;
	if (!identity) return "";
	const className =
		size === "small"
			? "provider-identity-placeholder provider-identity-placeholder--small"
			: "provider-identity-placeholder";
	const accent = identity.accentColor
		? ` style="--provider-accent: ${escapeHtml(identity.accentColor)}"`
		: "";
	if (identity.logo) {
		return `<img class="provider-identity-logo" src="${escapeHtml(identity.logo)}" alt="${escapeHtml(identity.displayName)} logo"${accent}>`;
	}
	return `<span class="${className}" aria-hidden="true"${accent}>${escapeHtml(identity.fallbackLogo)}</span>`;
}

export const VisualRegistry = Object.freeze({
	providers: ProviderRegistry.providers,
	getProvider,
	listProviders,
	renderLogo,
	renderBadge,
});
