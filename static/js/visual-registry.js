/* Visual identity contract: UI icons, provider marks, and status visuals stay separate. */
(function registerVisualIdentity(global) {
	const providerDefinitions = [
		["openrouter", "OpenRouter", false],
		["openai", "OpenAI", false],
		["anthropic", "Anthropic", false],
		["google", "Google (Gemini)", false],
		["grok", "xAI (Grok)", false],
		["groq", "Groq", false],
		["deepseek", "DeepSeek", false],
		["cerebras", "Cerebras", false],
		["chutes", "Chutes", false],
		["ollama", "Ollama (Local)", true],
		["custom_openai", "Custom OpenAI", true],
		["custom_anthropic", "Custom Anthropic", true],
	].map(([id, displayName, custom]) => ({
		id,
		displayName,
		custom,
		logo: null,
		accentColor: null,
		fallbackIcon: "provider",
		badge: null,
	}));

	const providers = Object.freeze(
		Object.fromEntries(
			providerDefinitions.map((provider) => [
				provider.id,
				Object.freeze(provider),
			]),
		),
	);

	const fallbackProvider = Object.freeze({
		id: "unknown",
		displayName: "Unknown provider",
		custom: false,
		logo: null,
		accentColor: null,
		fallbackIcon: "provider",
		badge: null,
	});

	global.VisualRegistry = Object.freeze({
		providers,
		getProvider(id) {
			return providers[id] || fallbackProvider;
		},
		listProviders() {
			return Object.values(providers);
		},
	});
})(window);
