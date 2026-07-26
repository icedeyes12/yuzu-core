/* Visual identity contract: UI icons, provider marks, and status visuals stay separate. */
(function registerVisualIdentity(global) {
	const providerDefinitions = [
		{
			id: "openrouter",
			displayName: "OpenRouter",
			shortName: "OpenRouter",
			family: "OpenAI-compatible",
			logo: null,
			fallbackLogo: "OR",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "openai",
			displayName: "OpenAI",
			shortName: "OpenAI",
			family: "OpenAI",
			logo: null,
			fallbackLogo: "OA",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "anthropic",
			displayName: "Anthropic",
			shortName: "Claude",
			family: "Anthropic",
			logo: null,
			fallbackLogo: "CL",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "google",
			displayName: "Google Gemini",
			shortName: "Gemini",
			family: "Google",
			logo: null,
			fallbackLogo: "GE",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "grok",
			displayName: "xAI (Grok)",
			shortName: "Grok",
			family: "xAI",
			logo: null,
			fallbackLogo: "GR",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "groq",
			displayName: "Groq",
			shortName: "Groq",
			family: "Groq",
			logo: null,
			fallbackLogo: "GQ",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "deepseek",
			displayName: "DeepSeek",
			shortName: "DeepSeek",
			family: "DeepSeek",
			logo: null,
			fallbackLogo: "DS",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "cerebras",
			displayName: "Cerebras",
			shortName: "Cerebras",
			family: "Cerebras",
			logo: null,
			fallbackLogo: "CE",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "chutes",
			displayName: "Chutes",
			shortName: "Chutes",
			family: "Chutes",
			logo: null,
			fallbackLogo: "CH",
			accentColor: null,
			badge: "official",
			supportsDark: true,
			custom: false,
			experimental: false,
			deprecated: false,
		},
		{
			id: "ollama",
			displayName: "Ollama (Local)",
			shortName: "Ollama",
			family: "Ollama",
			logo: null,
			fallbackLogo: "OL",
			accentColor: null,
			badge: "local",
			supportsDark: true,
			custom: true,
			experimental: false,
			deprecated: false,
		},
		{
			id: "custom_openai",
			displayName: "Custom OpenAI",
			shortName: "Custom",
			family: "Custom",
			logo: null,
			fallbackLogo: "CU",
			accentColor: null,
			badge: "custom",
			supportsDark: true,
			custom: true,
			experimental: false,
			deprecated: false,
		},
		{
			id: "custom_anthropic",
			displayName: "Custom Anthropic",
			shortName: "Custom",
			family: "Custom",
			logo: null,
			fallbackLogo: "CU",
			accentColor: null,
			badge: "custom",
			supportsDark: true,
			custom: true,
			experimental: false,
			deprecated: false,
		},
	];

	const providers = Object.freeze(
		Object.fromEntries(
			providerDefinitions.map((provider) => [
				provider.id,
				Object.freeze(provider),
			]),
		),
	);

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

	const fallbackProvider = Object.freeze({
		id: "unknown",
		displayName: "Unknown provider",
		shortName: "Unknown",
		family: "Vendor",
		logo: null,
		fallbackLogo: "??",
		accentColor: null,
		badge: "unknown",
		supportsDark: true,
		custom: false,
		experimental: false,
		deprecated: false,
	});

	function escapeHtml(value) {
		const node = document.createElement("span");
		node.textContent = String(value ?? "");
		return node.innerHTML;
	}

	function renderLogo(provider, size = "default") {
		const identity = provider || fallbackProvider;
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

	function renderBadge(provider) {
		const identity = provider || fallbackProvider;
		const label = badgeLabels[identity.badge] || badgeLabels.unknown;
		return `<span class="provider-identity-badge provider-identity-badge--${escapeHtml(identity.badge)}">${label}</span>`;
	}

	global.VisualRegistry = Object.freeze({
		providers,
		getProvider(id) {
			return providers[id] || fallbackProvider;
		},
		listProviders() {
			return Object.values(providers);
		},
		renderLogo,
		renderBadge,
	});
})(window);
