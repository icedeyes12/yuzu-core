/* Stable facade for presentation consumers; identity concerns live in focused registries. */
(function registerVisualFacade(global) {
	function escapeHtml(value) {
		const node = document.createElement("span");
		node.textContent = String(value ?? "");
		return node.innerHTML;
	}
	function renderLogo(provider, size = "default") {
		const identity = provider || global.ProviderRegistry?.fallback;
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

	global.VisualRegistry = Object.freeze({
		get providers() {
			return global.ProviderRegistry?.providers || {};
		},
		getProvider(id) {
			return global.ProviderRegistry?.get(id);
		},
		listProviders() {
			return global.ProviderRegistry?.list() || [];
		},
		renderLogo,
		renderBadge(...args) {
			return global.BadgeRegistry?.render(...args) || "";
		},
	});
})(window);
