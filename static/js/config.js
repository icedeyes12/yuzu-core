// FILE: static/js/config.js
// DESCRIPTION: Configuration page functionality

// Global config state (populated from /api/config)
let appConfig = null;

function setTextIfExists(id, value) {
	const el = document.getElementById(id);
	if (el) el.textContent = String(value ?? "");
}

function setValueIfExists(id, value) {
	const el = document.getElementById(id);
	if (el) el.value = value ?? "";
}

function getValueIfExists(id, fallback = "") {
	const el = document.getElementById(id);
	return el ? el.value : fallback;
}

function getCheckedIfExists(id) {
	const el = document.getElementById(id);
	return Boolean(el?.checked);
}

function getNumberIfExists(id, fallback = 0) {
	const raw = getValueIfExists(id, "");
	const num = Number(raw);
	return Number.isFinite(num) ? num : fallback;
}

function getProfileAdvancedSource(data) {
	return data?.advanced || data?.profile || data || {};
}

document.addEventListener("DOMContentLoaded", () => {
	console.log("Config page loaded - initializing...");
	loadAppConfig().then(() => {
		loadProfileData();
		loadGlobalKnowledge();
		loadProviderSettings();
		loadImageModel();
		loadVisionModel();
		setupEventListeners();
		loadBYOKConfig();
		initializeConfigAnimations();
	});
});

// Load application configuration from backend (SSOT)
async function loadAppConfig() {
	try {
		const response = await fetch("/api/config");
		const data = await response.json();

		if (data.status === "success") {
			appConfig = data;
			console.log("App config loaded:", appConfig);
			loadAdvancedSettingsFromData(appConfig.profile || appConfig);
		} else {
			console.error("Failed to load app config:", data);
		}
	} catch (error) {
		console.error("Error loading app config:", error);
	}
}

// Load profile data with proper global profile display
async function loadProfileData() {
	try {
		const response = await fetch("/api/profile");
		const data = await response.json();

		console.log("Full profile data:", data);

		const profileMemory = data.memory || {};
		const keyFacts = profileMemory.key_facts || {};

		setTextIfExists(
			"player-summary",
			profileMemory.player_summary ||
				"No global profile yet. Start chatting or update it from the buttons below.",
		);
		setTextIfExists(
			"player-likes",
			Array.isArray(keyFacts.likes) && keyFacts.likes.length > 0
				? keyFacts.likes.join(", ")
				: "None yet",
		);
		setTextIfExists(
			"player-dislikes",
			Array.isArray(keyFacts.dislikes) && keyFacts.dislikes.length > 0
				? keyFacts.dislikes.join(", ")
				: "None yet",
		);
		setTextIfExists(
			"player-personality",
			Array.isArray(keyFacts.personality_traits) &&
				keyFacts.personality_traits.length > 0
				? keyFacts.personality_traits.join(", ")
				: "None yet",
		);
		setTextIfExists(
			"player-memories",
			Array.isArray(keyFacts.important_memories) &&
				keyFacts.important_memories.length > 0
				? keyFacts.important_memories.join(", ")
				: "None yet",
		);
		setTextIfExists(
			"player-relationship",
			profileMemory.relationship_dynamics || "No relationship dynamics yet",
		);
		setTextIfExists(
			"global-profile-last-updated",
			profileMemory.last_global_summary || "Never",
		);

		setTextIfExists("affection-value", data.affection);
		setValueIfExists("affection-level", data.affection);
		setValueIfExists("display-name", data.user_name || "");
		setValueIfExists("partner-name", data.partner_name || "");
		setValueIfExists("persona-preset", data.persona_preset || "warm");
		setValueIfExists("persona-prompt", data.persona_prompt || "");

		const prefProvider = data.providers_config?.preferred_provider;
		const prefModel = data.providers_config?.preferred_model;
		setTextIfExists(
			"current-provider",
			prefProvider && prefModel
				? `${prefProvider}/${prefModel}`
				: prefProvider || "Not set",
		);

		const visPrefs = data.providers_config?.vision_model_preferences || {};
		setTextIfExists(
			"current-vision-model",
			visPrefs.provider && visPrefs.model
				? `${visPrefs.provider}/${visPrefs.model}`
				: "Not set",
		);

		loadMemoryStats();
		loadAdvancedSettingsFromData(data);
		loadGlobalKnowledge();
	} catch (error) {
		console.error("Error loading profile data:", error);
		setTextIfExists("player-summary", "Error loading global profile");
		showError("Failed to load profile data");
	}
}

// Load provider settings
async function loadProviderSettings() {
	try {
		const response = await fetch("/api/providers/list");
		const data = await response.json();

		if (data.status !== "success") {
			showError(data.message || "Failed to load providers");
			return;
		}

		const grid = document.getElementById("providers-grid");
		if (!grid) return;
		grid.innerHTML = "";

		const byok = JSON.parse(
			localStorage.getItem(window.BYOK_STORAGE_KEY) || "{}",
		);

		setTextIfExists(
			"current-provider",
			data.current_provider && data.current_model
				? `${data.current_provider}/${data.current_model}`
				: data.current_provider || "Not set",
		);

		const providersList = [
			{ id: "openrouter", name: "OpenRouter", custom: false },
			{ id: "openai", name: "OpenAI", custom: false },
			{ id: "anthropic", name: "Anthropic", custom: false },
			{ id: "google", name: "Google (Gemini)", custom: false },
			{ id: "grok", name: "xAI (Grok)", custom: false },
			{ id: "groq", name: "Groq", custom: false },
			{ id: "deepseek", name: "DeepSeek", custom: false },
			{ id: "cerebras", name: "Cerebras", custom: false },
			{ id: "chutes", name: "Chutes", custom: false },
			{ id: "ollama", name: "Ollama (Local)", custom: true },
			{ id: "custom_openai", name: "Custom OpenAI", custom: true },
			{ id: "custom_anthropic", name: "Custom Anthropic", custom: true },
		];

		providersList.forEach((provObj) => {
			const provider = provObj.id;
			const isCustom = provObj.custom;
			const isActive = provider === data.providers_config?.preferred_provider;

			const card = document.createElement("div");
			card.className = `provider-card ${isActive ? "active-provider" : ""}`;
			const titleHtml = `${provObj.name} ${isActive ? "<span class='badge-active'>Active</span>" : ""}`;

			let innerHtml = `
				<div class="provider-header" role="button" tabindex="0" aria-expanded="${isActive ? "true" : "false"}" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center;">
					<h3 style="margin: 0;">${titleHtml}</h3>
					<span style="font-size: 1.2rem;">${isActive ? "▼" : "▲"}</span>
				</div>
				<div class="provider-body" style="display: ${isActive ? "block" : "none"}; padding-top: 1rem;">
					<div class="form-group">
						<label for="key-${provider}">API Key (Saved in browser)</label>
						<div style="display: flex; gap: 10px;">
							<input type="password" id="key-${provider}" style="flex: 1;" placeholder="sk-..." value="${byok[provider]?.api_key || ""}">
							<button class="btn btn-secondary btn-sm save-byok-btn" type="button" data-provider="${provider}">Save Key</button>
						</div>
					</div>
			`;

			if (isCustom) {
				innerHtml += `
					<div class="form-group">
						<label for="url-${provider}">Base URL</label>
						<input type="text" id="url-${provider}" placeholder="https://api.openai.com/v1" value="${byok[provider]?.base_url || ""}">
					</div>
				`;
			}

			innerHtml += `
					<div class="form-group">
						<label for="model-${provider}">Model</label>
						<div style="display: flex; gap: 10px;">
							<select id="model-${provider}" class="form-select" style="flex: 1;">
			`;

			const modelsForThisProv = data.all_models?.[provider] || [];
			if (modelsForThisProv.length > 0) {
				modelsForThisProv.forEach((m) => {
					const selected =
						isActive && m === data.providers_config?.preferred_model
							? "selected"
							: "";
					innerHtml += `<option value="${m}" ${selected}>${m}</option>`;
				});
			} else {
				if (isActive && data.providers_config?.preferred_model) {
					innerHtml += `<option value="${data.providers_config.preferred_model}" selected>${data.providers_config.preferred_model}</option>`;
				} else {
					innerHtml += `<option value="">Fetch models first...</option>`;
				}
			}

			innerHtml += `
							</select>
							<button class="btn btn-info btn-sm fetch-models-btn" type="button" data-provider="${provider}">Refresh Models</button>
						</div>
					</div>
					<div class="config-actions" style="margin-top: 1.5rem; display: flex; gap: 10px;">
						<button class="btn btn-primary set-active-btn" type="button" data-provider="${provider}">Set as Active</button>
						<button class="btn btn-success test-conn-btn" type="button" data-provider="${provider}">Test Connection</button>
					</div>
				</div>
			`;

			card.innerHTML = innerHtml;
			grid.appendChild(card);

			// Add accordion toggle
			const header = card.querySelector(".provider-header");
			const body = card.querySelector(".provider-body");
			const icon = header.querySelector("span:last-child");

			// Set initial icon
			if (icon) icon.textContent = isActive ? "▲" : "▼";

			header.addEventListener("click", () => {
				const isExpanded = body.style.display === "block";
				body.style.display = isExpanded ? "none" : "block";
				header.setAttribute("aria-expanded", !isExpanded);
				if (icon) icon.textContent = isExpanded ? "▼" : "▲";
			});
		});

		document.querySelectorAll(".save-byok-btn").forEach((btn) => {
			btn.addEventListener("click", (e) =>
				saveBYOKForProvider(e.currentTarget.dataset.provider),
			);
		});
		document.querySelectorAll(".fetch-models-btn").forEach((btn) => {
			btn.addEventListener("click", (e) =>
				fetchModelsForProvider(e.currentTarget.dataset.provider),
			);
		});
		document.querySelectorAll(".set-active-btn").forEach((btn) => {
			btn.addEventListener("click", (e) =>
				setProviderActive(e.currentTarget.dataset.provider),
			);
		});
		document.querySelectorAll(".test-conn-btn").forEach((btn) => {
			btn.addEventListener("click", (e) =>
				testProviderConnection(e.currentTarget.dataset.provider),
			);
		});
	} catch (error) {
		console.error("Error loading provider settings:", error);
		showError("Error loading provider settings");
	}
}

function saveBYOKForProvider(provider) {
	const byok = JSON.parse(
		localStorage.getItem(window.BYOK_STORAGE_KEY) || "{}",
	);
	const keyInput = document.getElementById(`key-${provider}`);
	if (!keyInput) return;

	if (!byok[provider]) byok[provider] = {};
	byok[provider].api_key = keyInput.value;

	if (provider.startsWith("custom")) {
		const baseInput = document.getElementById(`url-${provider}`);
		byok[provider].base_url = baseInput?.value || "";
	}

	localStorage.setItem(window.BYOK_STORAGE_KEY, JSON.stringify(byok));
	showSuccess(`${provider} key saved in browser.`);
}

async function fetchModelsForProvider(provider) {
	const btn = document.querySelector(
		`.fetch-models-btn[data-provider="${provider}"]`,
	);
	if (btn) {
		btn.disabled = true;
		btn.textContent = "Fetching...";
	}

	try {
		const byok = JSON.parse(
			localStorage.getItem(window.BYOK_STORAGE_KEY) || "{}",
		);
		const provConfig = byok[provider] || {};

		const headers = {};
		if (provConfig.api_key) headers["X-Provider-Key"] = provConfig.api_key;
		if (provConfig.base_url)
			headers["X-Provider-BaseUrl"] = provConfig.base_url;

		const response = await fetch(`/api/proxy/models/${provider}`, { headers });
		const data = await response.json();

		if (data.status === "success" && data.models) {
			const select = document.getElementById(`model-${provider}`);
			if (select) {
				select.innerHTML = "";
				data.models.forEach((model) => {
					const opt = document.createElement("option");
					opt.value = model;
					opt.textContent = model;
					select.appendChild(opt);
				});
			}
			showSuccess(`Models loaded for ${provider}.`);
		} else {
			showError(`Failed to fetch models: ${data.message || "Unknown error"}`);
		}
	} catch (err) {
		console.error(err);
		showError("Network error while fetching models");
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.textContent = "Refresh Models";
		}
	}
}

// Update model dropdown based on selected provider
function updateModelDropdown(provider, allModels, currentModel = "") {
	const modelSelect = document.getElementById("ai-model");
	if (!modelSelect) return;
	modelSelect.innerHTML = "";

	const models = allModels[provider] || [];
	if (models.length === 0) {
		const option = document.createElement("option");
		option.value = "";
		option.textContent = "No models available";
		modelSelect.appendChild(option);
		return;
	}

	models.forEach((model) => {
		const option = document.createElement("option");
		option.value = model;
		option.textContent = model;
		if (model === currentModel) option.selected = true;
		modelSelect.appendChild(option);
	});

	console.log(`Updated model dropdown for ${provider}`);
}

// Test provider connection
async function testProviderConnection(providerName) {
	const statusElement = document.getElementById("connection-status");
	if (!statusElement) return;
	statusElement.textContent = "Testing...";
	statusElement.className = "status-checking";
	statusElement.classList.add("pulse");

	try {
		const headers = { "Content-Type": "application/json" };
		try {
			const raw = localStorage.getItem(window.BYOK_STORAGE_KEY);
			if (raw) headers["X-BYOK-Config"] = btoa(encodeURIComponent(raw));
		} catch (e) {
			console.warn("Error attaching BYOK config for test:", e);
		}

		const response = await fetch("/api/providers/test_connection", {
			method: "POST",
			headers: headers,
			body: JSON.stringify({ provider_name: providerName }),
		});

		const result = await response.json();
		statusElement.classList.remove("pulse");

		if (result.status === "success") {
			statusElement.textContent = result.connected
				? "Connected"
				: "Connection failed";
			statusElement.className = result.connected
				? "status-connected"
				: "status-disconnected";
			if (result.connected) {
				showSuccess(`${providerName} connection successful!`);
			} else {
				showError(`${providerName} connection failed`);
			}
		} else {
			statusElement.textContent = "Test failed";
			statusElement.className = "status-disconnected";
			showError("Provider test failed");
		}
	} catch (error) {
		console.error("Error testing provider connection:", error);
		statusElement.classList.remove("pulse");
		statusElement.textContent = "Test error";
		statusElement.className = "status-disconnected";
		showError("Error testing provider connection");
	}
}

function setupEventListeners() {
	console.log("Setting up config event listeners...");

	const saveProfileBtn = document.getElementById("save-profile");
	if (saveProfileBtn)
		saveProfileBtn.addEventListener("click", saveProfileSettings);

	const visionProviderSelect = document.getElementById("vision-provider");
	const testVisionBtn = document.getElementById("test-vision");
	const saveVisionModelBtn = document.getElementById("save-vision-model");
	if (visionProviderSelect) {
		visionProviderSelect.addEventListener("change", function () {
			updateVisionModelDropdown(this.value);
		});
	}
	if (testVisionBtn) testVisionBtn.addEventListener("click", testVisionModel);
	if (saveVisionModelBtn)
		saveVisionModelBtn.addEventListener("click", saveVisionModel);

	document.addEventListener("keydown", (e) => {
		if (
			(e.ctrlKey || e.metaKey) &&
			e.key === "s" &&
			e.target.tagName !== "TEXTAREA"
		) {
			e.preventDefault();
			saveProfileSettings();
		}
		if (e.key === "Escape") {
			const sidebar = document.getElementById("mainSidebar");
			if (sidebar?.classList.contains("open")) {
				toggleSidebar();
			}
		}
	});

	const tempSlider = document.getElementById("adv-temperature");
	if (tempSlider) {
		tempSlider.addEventListener("input", (e) => {
			const out = document.getElementById("val-temperature");
			if (out) out.textContent = parseFloat(e.target.value).toFixed(1);
		});
	}

	const topPSlider = document.getElementById("adv-top-p");
	if (topPSlider) {
		topPSlider.addEventListener("input", (e) => {
			const out = document.getElementById("val-top-p");
			if (out) out.textContent = parseFloat(e.target.value).toFixed(2);
		});
	}

	const saveAdvancedBtn = document.getElementById("save-advanced-settings");
	if (saveAdvancedBtn)
		saveAdvancedBtn.addEventListener("click", saveAdvancedSettings);

	const saveImageModelBtn = document.getElementById("save-image-model");
	if (saveImageModelBtn)
		saveImageModelBtn.addEventListener("click", saveImageModel);

	const saveGlobalKnowledgeBtn = document.getElementById(
		"save-global-knowledge",
	);
	if (saveGlobalKnowledgeBtn)
		saveGlobalKnowledgeBtn.addEventListener("click", saveGlobalKnowledge);

	const updateGlobalProfileBtn = document.getElementById(
		"update-global-profile",
	);
	if (updateGlobalProfileBtn)
		updateGlobalProfileBtn.addEventListener("click", updateGlobalProfile);

	const clearChatHistoryBtn = document.getElementById("clear-chat-history");
	if (clearChatHistoryBtn)
		clearChatHistoryBtn.addEventListener("click", clearChatHistory);

	const rebuildMemoryBtn = document.getElementById("rebuild-memory");
	if (rebuildMemoryBtn)
		rebuildMemoryBtn.addEventListener("click", rebuildStructuredMemory);

	const runDecayBtn = document.getElementById("run-decay");
	if (runDecayBtn) runDecayBtn.addEventListener("click", runMemoryDecay);

	const saveLocationBtn = document.getElementById("save-location");
	if (saveLocationBtn) saveLocationBtn.addEventListener("click", saveLocation);

	console.log("Event listeners setup complete");
}

// Load image model on page load
async function loadImageModel() {
	try {
		const response = await fetch("/api/profile");
		const data = await response.json();

		const imageModel = data.image_model || "qwen_image";
		const select = document.getElementById("image-model");
		if (!select) return;

		const availableModels = [
			{ value: "qwen_image", label: "Qwen Image" },
			{ value: "z_turbo", label: "Z Image Turbo" },
		];
		select.innerHTML = "";
		availableModels.forEach((m) => {
			const option = document.createElement("option");
			option.value = m.value;
			option.textContent = m.label;
			if (m.value === imageModel) option.selected = true;
			select.appendChild(option);
		});

		setTextIfExists("current-image-model", imageModel);
		console.log("Image model loaded:", imageModel);
	} catch (error) {
		console.error("Error loading image model:", error);
	}
}

// Load vision model on page load
async function loadVisionModel() {
	if (!appConfig) {
		await loadAppConfig();
	}

	const visionConfig = appConfig?.vision || {};
	const currentProvider = visionConfig.current_provider || "";
	const currentModel = visionConfig.current_model || "";

	const visionProviderSelect = document.getElementById("vision-provider");
	const visionModelSelect = document.getElementById("vision-model");
	if (!visionProviderSelect || !visionModelSelect) return;

	visionProviderSelect.innerHTML = "";
	const visionProviders = Object.keys(visionConfig.models_by_provider || {});
	if (visionProviders.length === 0) {
		visionProviders.push("chutes", "openrouter");
	}

	visionProviders.forEach((provider) => {
		const option = document.createElement("option");
		option.value = provider;
		option.textContent = provider.charAt(0).toUpperCase() + provider.slice(1);
		if (provider === currentProvider) option.selected = true;
		visionProviderSelect.appendChild(option);
	});

	updateVisionModelDropdown(currentProvider, currentModel);
	setTextIfExists(
		"current-vision-model",
		currentProvider && currentModel
			? `${currentProvider}/${currentModel}`
			: "Not set",
	);

	console.log("Vision model loaded from config");
}

function updateVisionModelDropdown(provider, currentModel = "") {
	const visionModelSelect = document.getElementById("vision-model");
	if (!visionModelSelect) return;
	visionModelSelect.innerHTML = "";

	const models = appConfig?.vision?.models_by_provider?.[provider] || [];

	if (models.length === 0) {
		const option = document.createElement("option");
		option.value = "";
		option.textContent = "No vision models available";
		visionModelSelect.appendChild(option);
		return;
	}

	models.forEach((model) => {
		const option = document.createElement("option");
		option.value = model;
		option.textContent = model;
		if (model === currentModel) option.selected = true;
		visionModelSelect.appendChild(option);
	});

	console.log(
		`Updated vision model dropdown for ${provider}: ${models.length} models`,
	);
}

async function testVisionModel() {
	const provider = getValueIfExists("vision-provider", "");
	const model = getValueIfExists("vision-model", "");

	if (!provider || !model) {
		showError("Please select both provider and model");
		return;
	}

	const statusElement = document.getElementById("current-vision-model");
	if (statusElement) statusElement.textContent = "Testing...";

	try {
		const response = await fetch("/api/providers/test_vision", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ provider, model }),
		});

		const result = await response.json();

		if (result.success) {
			if (statusElement) statusElement.textContent = `${provider}/${model}`;
			showSuccess("Vision model is available!");
		} else {
			if (statusElement)
				statusElement.textContent = `${provider}/${model} (may not support vision)`;
			showError(result.message || "Vision model test failed");
		}
	} catch (error) {
		console.error("Error testing vision model:", error);
		if (statusElement) statusElement.textContent = `${provider}/${model}`;
		showError("Vision model test error");
	}
}

async function saveVisionModel() {
	const provider = getValueIfExists("vision-provider", "");
	const model = getValueIfExists("vision-model", "");

	if (!provider) {
		showError("Please select a vision provider");
		return;
	}

	if (!model) {
		showError("Please select a vision model");
		return;
	}

	const saveBtn = document.getElementById("save-vision-model");
	if (!saveBtn) return;
	const originalText = saveBtn.textContent;
	saveBtn.textContent = "Saving...";
	saveBtn.disabled = true;

	try {
		const response = await fetch("/api/providers/set_vision_model", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ provider, model }),
		});

		const result = await response.json();

		if (result.status === "success") {
			setTextIfExists("current-vision-model", `${provider}/${model}`);
			showSuccess("Vision model saved!");
		} else {
			showError(`Failed to save vision model: ${result.message}`);
		}
	} catch (error) {
		console.error("Error saving vision model:", error);
		showError("Error saving vision model");
	} finally {
		saveBtn.textContent = originalText;
		saveBtn.disabled = false;
	}
}

// Save image model setting
async function saveImageModel() {
	const select = document.getElementById("image-model");
	if (!select) return;

	const btn = document.getElementById("save-image-model");
	if (!btn) return;
	const originalText = btn.textContent;
	btn.textContent = "Saving...";
	btn.disabled = true;

	try {
		const imageModel =
			select.value === "qwen_image" ? "qwen_image" : select.value;
		const response = await fetch("/api/update_profile", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ updates: { image_model: imageModel } }),
		});
		if (response.ok) {
			setTextIfExists("current-image-model", imageModel);
			showSuccess("Image model saved successfully!");
		} else {
			showError("Error saving image model");
		}
	} catch (error) {
		console.error("Error saving image model:", error);
		showError("Error saving image model");
	} finally {
		btn.textContent = originalText;
		btn.disabled = false;
	}
}

// Save provider settings
async function setProviderActive(providerName) {
	const modelSelect = document.getElementById(`model-${providerName}`);
	if (!modelSelect) {
		showError("Model selection not found for this provider");
		return;
	}

	const modelName = modelSelect.value;
	if (!modelName) {
		showError("Please select a model first (fetch models if empty)");
		return;
	}

	const saveBtn = document.querySelector(
		`.set-active-btn[data-provider="${providerName}"]`,
	);
	if (saveBtn) {
		saveBtn.textContent = "Saving...";
		saveBtn.disabled = true;
	}

	try {
		const response = await fetch("/api/providers/set_preferred", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
			},
			body: JSON.stringify({
				provider_name: providerName,
				model_name: modelName,
			}),
		});

		const result = await response.json();

		if (result.status === "success") {
			showSuccess(`${providerName} set as active!`);
			setTextIfExists("current-provider", `${providerName}/${modelName}`);

			// Update UI to reflect new active state
			document.querySelectorAll(".provider-card").forEach((card) => {
				card.classList.remove("active-provider");
				const badge = card.querySelector(".badge-active");
				if (badge) badge.remove();
			});

			const activeCard = saveBtn.closest(".provider-card");
			if (activeCard) {
				activeCard.classList.add("active-provider");
				const h3 = activeCard.querySelector("h3");
				if (h3 && !h3.querySelector(".badge-active")) {
					h3.innerHTML += " <span class='badge-active'>Active</span>";
				}
			}
		} else {
			showError(`Failed to set active provider: ${result.message}`);
		}
	} catch (error) {
		console.error("Error setting active provider:", error);
		showError("Error setting active provider");
	} finally {
		if (saveBtn) {
			saveBtn.textContent = "Set as Active";
			saveBtn.disabled = false;
		}
	}
}

async function saveProfileSettings() {
	const displayName = getValueIfExists("display-name", "");
	const partnerName = getValueIfExists("partner-name", "");
	const affection = getValueIfExists("affection-level", "0");
	const personaPreset = getValueIfExists("persona-preset", "warm");
	const personaPrompt = getValueIfExists("persona-prompt", "");

	if (!displayName.trim()) {
		showError("Display name is required");
		return;
	}

	if (!partnerName.trim()) {
		showError("Partner name is required");
		return;
	}

	const saveBtn = document.getElementById("save-profile");
	if (!saveBtn) return;
	const originalText = saveBtn.textContent;
	saveBtn.textContent = "Saving...";
	saveBtn.disabled = true;

	try {
		const response = await fetch("/api/update_profile", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
			},
			body: JSON.stringify({
				updates: {
					user_name: displayName,
					partner_name: partnerName,
					affection: parseInt(affection, 10),
					persona_preset: personaPreset,
					persona_prompt: personaPrompt,
				},
			}),
		});

		if (response.ok) {
			showSuccess("Profile settings saved successfully!");
			loadProfileData();
		} else {
			showError("Error saving profile settings");
		}
	} catch (error) {
		console.error("Error saving profile:", error);
		showError("Error saving profile settings");
	} finally {
		saveBtn.textContent = originalText;
		saveBtn.disabled = false;
	}
}

function loadAdvancedSettingsFromData(data) {
	const source = getProfileAdvancedSource(data);
	setValueIfExists("adv-temperature", source.temperature ?? 1.0);
	setValueIfExists("adv-top-p", source.top_p ?? 1.0);
	setValueIfExists("adv-max-tokens", source.max_tokens ?? 4096);
	setValueIfExists("adv-history-limit", source.history_limit ?? 20);
	const reasoning = document.getElementById("adv-reasoning");
	if (reasoning) reasoning.checked = Boolean(source.enable_reasoning);
	const vision = document.getElementById("adv-vision");
	if (vision) vision.checked = Boolean(source.enable_vision);
	const tempOut = document.getElementById("val-temperature");
	if (tempOut)
		tempOut.textContent = Number(source.temperature ?? 1.0).toFixed(1);
	const topPOut = document.getElementById("val-top-p");
	if (topPOut) topPOut.textContent = Number(source.top_p ?? 1.0).toFixed(2);
}

async function saveAdvancedSettings() {
	const saveBtn = document.getElementById("save-advanced-settings");
	if (!saveBtn) return;
	const originalText = saveBtn.textContent;
	saveBtn.textContent = "Saving...";
	saveBtn.disabled = true;

	try {
		const updates = {
			temperature: getNumberIfExists("adv-temperature", 1.0),
			top_p: getNumberIfExists("adv-top-p", 1.0),
			max_tokens: getNumberIfExists("adv-max-tokens", 4096),
			history_limit: getNumberIfExists("adv-history-limit", 20),
			enable_reasoning: getCheckedIfExists("adv-reasoning"),
			enable_vision: getCheckedIfExists("adv-vision"),
		};

		const response = await fetch("/api/update_profile", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ updates }),
		});

		if (response.ok) {
			showSuccess("Advanced settings saved");
			loadAdvancedSettingsFromData(updates);
		} else {
			showError("Error saving advanced settings");
		}
	} catch (error) {
		console.error("Error saving advanced settings:", error);
		showError("Error saving advanced settings");
	} finally {
		saveBtn.textContent = originalText;
		saveBtn.disabled = false;
	}
}

// === BYOK (Bring Your Own Key) — localStorage only, zero server storage ===
const BYOK_STORAGE_KEY = window.BYOK_STORAGE_KEY || "yuzu_byok_config";

function saveBYOKConfig() {
	const provider = document.getElementById("byok-provider")?.value || "";
	const apiKey = document.getElementById("byok-api-key")?.value?.trim() || "";
	const baseUrl = document.getElementById("byok-base-url")?.value?.trim() || "";
	const modelId = document.getElementById("byok-model-id")?.value?.trim() || "";

	if (!provider) {
		showError("Please select a provider");
		return;
	}

	const config = { provider, apiKey, baseUrl, modelId };

	try {
		localStorage.setItem(BYOK_STORAGE_KEY, JSON.stringify(config));

		const btn = document.getElementById("save-byok");
		if (btn) {
			const original = btn.textContent;
			btn.textContent = "Saved ✓";
			btn.style.background = "var(--accent-tertiary)";
			setTimeout(() => {
				btn.textContent = original;
				btn.style.background = "";
			}, 1800);
		}
		showSuccess("Provider configuration saved locally");
	} catch (e) {
		console.error("saveBYOKConfig failed:", e);
		showError("Failed to save provider configuration locally");
	}
}

function loadBYOKConfig() {
	console.log("BYOK config handled via card UI now.");
}

function toggleBYOKFields() {
	const provider = document.getElementById("byok-provider")?.value || "";
	const showConditional = provider === "ollama" || provider === "custom";
	const baseGroup = document.getElementById("byok-baseurl-group");
	const modelGroup = document.getElementById("byok-modelid-group");
	if (baseGroup) baseGroup.style.display = showConditional ? "block" : "none";
	if (modelGroup) modelGroup.style.display = showConditional ? "block" : "none";
}

window.saveBYOKConfig = saveBYOKConfig;

// Load structured memory statistics
async function loadMemoryStats() {
	try {
		const response = await fetch("/api/memory_stats");
		const data = await response.json();

		if (data.status === "success") {
			const stats = data.stats;
			setTextIfExists("semantic-count", stats.semantic || 0);
			setTextIfExists("episodic-count", stats.episodic || 0);
			setTextIfExists("segment-count", stats.segments || 0);

			const factsList = document.getElementById("top-facts-list");
			if (factsList) {
				if (stats.top_facts && stats.top_facts.length > 0) {
					factsList.innerHTML = stats.top_facts
						.map((f) => `<li>${f}</li>`)
						.join("");
				} else {
					factsList.innerHTML =
						'<li>No facts extracted yet. Start chatting or click "Rebuild Structured Memory".</li>';
				}
			}
		}
	} catch (error) {
		console.error("Error loading memory stats:", error);
	}
}

async function rebuildStructuredMemory() {
	if (
		!confirm(
			"Rebuild structured memory? This will re-extract facts and segments from the last 50 messages in the current session.",
		)
	) {
		return;
	}

	const btn = document.getElementById("rebuild-memory");
	if (!btn) return;
	const originalText = btn.textContent;
	btn.textContent = "Rebuilding...";
	btn.disabled = true;

	try {
		const response = await fetch("/api/rebuild_structured_memory", {
			method: "POST",
		});
		const result = await response.json();

		if (result.status === "success") {
			showSuccess(result.message);
			loadMemoryStats();
		} else {
			showError(`Failed to rebuild memory: ${result.message || result.error}`);
		}
	} catch (error) {
		console.error("Error rebuilding structured memory:", error);
		showError("Error rebuilding structured memory");
	} finally {
		btn.textContent = originalText;
		btn.disabled = false;
	}
}

async function runMemoryDecay() {
	if (
		!confirm(
			"Run memory decay? This applies FSRS-style forgetting: old unused memories will fade, frequently used ones will be preserved.",
		)
	) {
		return;
	}

	const btn = document.getElementById("run-decay");
	if (!btn) return;
	const originalText = btn.textContent;
	btn.textContent = "Running...";
	btn.disabled = true;

	try {
		const response = await fetch("/api/run_memory_decay", { method: "POST" });
		const result = await response.json();

		if (result.status === "success") {
			showSuccess(result.message);
			loadMemoryStats();
		} else {
			showError(`Failed to run decay: ${result.message || result.error}`);
		}
	} catch (error) {
		console.error("Error running memory decay:", error);
		showError("Error running memory decay");
	} finally {
		btn.textContent = originalText;
		btn.disabled = false;
	}
}

async function updateGlobalProfile() {
	if (
		!confirm(
			"Update global player profile? This will analyze ALL sessions to build a comprehensive profile. This may take a moment.",
		)
	) {
		return;
	}

	const updateBtn = document.getElementById("update-global-profile");
	if (!updateBtn) return;
	const originalText = updateBtn.textContent;
	updateBtn.textContent = "Analyzing...";
	updateBtn.disabled = true;

	try {
		const response = await fetch("/api/update_global_profile", {
			method: "POST",
		});
		const result = await response.json();

		if (result.status === "success") {
			showSuccess("Global player profile updated from ALL sessions!");
			if (result.profile?.memory) {
				updateGlobalProfileDisplay(result.profile.memory);
			} else {
				loadProfileData();
			}
		} else {
			showError(`Failed to update global profile: ${result.message}`);
		}
	} catch (error) {
		console.error("Error updating global profile:", error);
		showError("Error updating global profile");
	} finally {
		updateBtn.textContent = originalText;
		updateBtn.disabled = false;
	}
}

// Direct update function for global profile display
function updateGlobalProfileDisplay(profileMemory) {
	console.log("Updating global profile display with:", profileMemory);

	const keyFacts = profileMemory.key_facts || {};
	setTextIfExists(
		"player-summary",
		profileMemory.player_summary ||
			"Profile analysis completed but no summary generated.",
	);
	setTextIfExists(
		"player-likes",
		Array.isArray(keyFacts.likes) && keyFacts.likes.length > 0
			? keyFacts.likes.join(", ")
			: "None identified",
	);
	setTextIfExists(
		"player-dislikes",
		Array.isArray(keyFacts.dislikes) && keyFacts.dislikes.length > 0
			? keyFacts.dislikes.join(", ")
			: "None identified",
	);
	setTextIfExists(
		"player-personality",
		Array.isArray(keyFacts.personality_traits) &&
			keyFacts.personality_traits.length > 0
			? keyFacts.personality_traits.join(", ")
			: "None identified",
	);
	setTextIfExists(
		"player-memories",
		Array.isArray(keyFacts.important_memories) &&
			keyFacts.important_memories.length > 0
			? keyFacts.important_memories.join(", ")
			: "None identified",
	);
	setTextIfExists(
		"player-relationship",
		profileMemory.relationship_dynamics ||
			"No specific relationship dynamics identified",
	);
	setTextIfExists(
		"global-profile-last-updated",
		profileMemory.last_global_summary || "Just now",
	);
}

async function clearChatHistory() {
	if (
		!confirm(
			"Are you sure you want to clear all chat history in the current session? This cannot be undone.",
		)
	) {
		return;
	}

	const clearBtn = document.getElementById("clear-chat-history");
	if (!clearBtn) return;
	const originalText = clearBtn.textContent;
	clearBtn.textContent = "Clearing...";
	clearBtn.disabled = true;

	try {
		const response = await fetch("/api/clear_chat", { method: "POST" });
		if (response.ok) {
			showSuccess("Chat history cleared successfully!");
			loadProfileData();
		} else {
			showError("Error clearing chat history");
		}
	} catch (error) {
		console.error("Error clearing chat:", error);
		showError("Error clearing chat history");
	} finally {
		clearBtn.textContent = originalText;
		clearBtn.disabled = false;
	}
}

// Global knowledge functions
async function loadGlobalKnowledge() {
	try {
		const response = await fetch("/api/profile");
		const data = await response.json();

		const globalKnowledge = data.global_knowledge || {};
		let gkText = "";
		if (typeof globalKnowledge === "string") {
			gkText = globalKnowledge;
		} else if (globalKnowledge.facts) {
			gkText =
				typeof globalKnowledge.facts === "string"
					? globalKnowledge.facts
					: JSON.stringify(globalKnowledge.facts, null, 2);
		} else if (Object.keys(globalKnowledge).length > 0) {
			gkText = JSON.stringify(globalKnowledge, null, 2);
		}
		setValueIfExists("global-knowledge", gkText);

		console.log("Global knowledge loaded");
	} catch (error) {
		console.error("Error loading global knowledge:", error);
		showError("Failed to load global knowledge");
	}
}

async function saveGlobalKnowledge() {
	const facts = getValueIfExists("global-knowledge", "").trim();
	const saveBtn = document.getElementById("save-global-knowledge");
	if (!saveBtn) return;
	const originalText = saveBtn.textContent;
	saveBtn.textContent = "Saving...";
	saveBtn.disabled = true;

	try {
		const response = await fetch("/api/global_knowledge/update", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
			},
			body: JSON.stringify({ facts }),
		});

		const result = await response.json();
		if (result.status === "success") {
			showSuccess("Global knowledge saved! This will be used in all sessions.");
		} else {
			showError("Error saving global knowledge");
		}
	} catch (error) {
		console.error("Error saving global knowledge:", error);
		showError("Error saving global knowledge");
	} finally {
		saveBtn.textContent = originalText;
		saveBtn.disabled = false;
	}
}

// UI Helper Functions
function showSuccess(message) {
	showNotification(message, "success");
}

function showError(message) {
	showNotification(message, "error");
}

function showNotification(message, type = "info") {
	const existingNotifications = document.querySelectorAll(
		".config-notification",
	);
	existingNotifications.forEach((notification) => {
		notification.remove();
	});

	const escapeHtml = (text) => {
		const div = document.createElement("div");
		div.textContent = text;
		return div.innerHTML;
	};

	const notification = document.createElement("div");
	notification.className = `config-notification ${type}`;
	notification.innerHTML = `
		<div class="notification-content">
			<span class="notification-icon">${type === "success" ? "✓" : type === "error" ? "✗" : "ℹ"}</span>
			<span class="notification-message">${escapeHtml(message)}</span>
			<button class="notification-close" type="button" onclick="this.parentElement.parentElement.remove()">×</button>
		</div>
	`;

	notification.style.cssText = `
		position: fixed;
		top: 100px;
		right: 20px;
		background: ${type === "success" ? "var(--accent-mint)" : type === "error" ? "var(--accent-pink)" : "var(--accent-lavender)"};
		color: var(--button-text);
		padding: 1rem;
		border-radius: 8px;
		box-shadow: var(--shadow-soft);
		z-index: 10000;
		max-width: 300px;
		animation: slideInRight 0.3s ease;
	`;

	document.body.appendChild(notification);

	setTimeout(() => {
		if (notification.parentElement) {
			notification.remove();
		}
	}, 5000);
}

// Initialize config animations
function initializeConfigAnimations() {
	const observerOptions = {
		threshold: 0.1,
		rootMargin: "0px 0px -50px 0px",
	};

	const observer = new IntersectionObserver((entries) => {
		entries.forEach((entry) => {
			if (entry.isIntersecting) {
				entry.target.style.opacity = "1";
				entry.target.style.transform = "translateY(0)";
			}
		});
	}, observerOptions);

	document.querySelectorAll(".config-section").forEach((section) => {
		section.style.opacity = "0";
		section.style.transform = "translateY(20px)";
		section.style.transition = "opacity 0.6s ease, transform 0.6s ease";
		observer.observe(section);
	});

	console.log("Config animations initialized");
}

// Make functions globally available
window.showSuccess = showSuccess;
window.showError = showError;

// Location functions
async function loadLocation() {
	try {
		const response = await fetch("/api/profile");
		const data = await response.json();
		const ctx = data.context || {};
		const loc = ctx.location || {};
		setValueIfExists("location-lat", loc.lat || 0.0);
		setValueIfExists("location-lon", loc.lon || 0.0);
	} catch (e) {
		console.error("Failed to load location:", e);
	}
}

async function saveLocation() {
	const lat = parseFloat(getValueIfExists("location-lat", "0")) || 0.0;
	const lon = parseFloat(getValueIfExists("location-lon", "0")) || 0.0;

	try {
		const response = await fetch("/api/update_location", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ lat, lon }),
		});
		const data = await response.json();
		if (data.status === "success") {
			showSuccess("Location saved!");
		} else {
			showError(data.message || "Failed to save location");
		}
	} catch (e) {
		console.error("Error saving location:", e);
		showError("Failed to save location");
	}
}

function _useCurrentLocation() {
	if (!navigator.geolocation) {
		alert("Geolocation not supported.");
		return;
	}

	navigator.geolocation.getCurrentPosition(
		(pos) => {
			setValueIfExists("location-lat", pos.coords.latitude);
			setValueIfExists("location-lon", pos.coords.longitude);
		},
		(_err) => {
			alert("Location permission denied or unavailable.");
		},
	);
}

// Load location on page load
document.addEventListener("DOMContentLoaded", loadLocation);

// Load image model on page load
document.addEventListener("DOMContentLoaded", loadImageModel);

// Load vision model on page load
document.addEventListener("DOMContentLoaded", loadVisionModel);

// Export to window to fix unused variable warnings from HTML onclicks
window.clearChatHistory = clearChatHistory;
window.rebuildStructuredMemory = rebuildStructuredMemory;
window.runMemoryDecay = runMemoryDecay;
window.saveGlobalKnowledge = saveGlobalKnowledge;
window.saveImageModel = saveImageModel;
window.saveLocation = saveLocation;
window.setProviderActive = setProviderActive;
window.testProviderConnection = testProviderConnection;
window.toggleBYOKFields = toggleBYOKFields;
window.updateGlobalProfile = updateGlobalProfile;
window.updateModelDropdown = updateModelDropdown;
