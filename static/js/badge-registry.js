/* Badge labels and compatibility rendering for provider identity. */
(function registerBadgeRegistry(global) {
	const badgeLabels = Object.freeze({
		official: "Official",
		community: "Community",
		custom: "Custom",
		experimental: "Experimental",
		deprecated: "Deprecated",
		preview: "Preview",
		local: "Local",
		unknown: "Unknown",
	});

	function escapeHtml(value) {
		const node = document.createElement("span");
		node.textContent = String(value ?? "");
		return node.innerHTML;
	}

	function getLabel(badge) {
		return badgeLabels[badge] || badgeLabels.unknown;
	}

	function render(provider) {
		const identity = provider || global.ProviderRegistry?.fallback;
		if (!identity) return "";
		return `<span class="provider-identity-badge provider-identity-badge--${escapeHtml(identity.badge)}">${getLabel(identity.badge)}</span>`;
	}

	global.BadgeRegistry = Object.freeze({ badgeLabels, getLabel, render });
})(window);
