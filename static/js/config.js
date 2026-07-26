// FILE: static/js/config.js
// DESCRIPTION: Configuration page functionality

// Global config state (populated from /api/config)
let appConfig = null;
const PROVIDER_MODELS_CACHE_KEY = "yuzu_provider_models";
const PROVIDER_MODELS_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

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

document.addEventListener("DOMContentLoaded", async () => {
	console.log("Config page loaded - initializing...");
	await loadAppConfig();
	await Promise.all([
		loadProfileData(),
		loadGlobalKnowledge(),
		loadImageModel(),
	]);
	await loadProviderSettings();
	await loadVisionModel();
	setupEventListeners();
	loadBYOKConfig();
	initializeConfigAnimations();
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

// Load profile data for editable application settings
async function loadProfileData() {
	try {
		const response = await fetch("/api/profile");
		const data = await response.json();

		setTextIfExists("affection-value", data.affection);
		setValueIfExists("affection-level", data.affection);
		setValueIfExists("display-name", data.user_name || "");
		setValueIfExists("partner-name", data.partner_name || "");
		setValueIfExists("persona-preset", data.persona_preset || "helpful");
		setValueIfExists("persona-prompt", data.persona_prompt || "");

		const visPrefs = data.providers_config?.vision_model_preferences || {};
		setTextIfExists(
			"current-vision-model",
			visPrefs.provider && visPrefs.model
				? `${visPrefs.provider}/${visPrefs.model}`
				: "Not set",
		);

		loadAdvancedSettingsFromData(data);
	} catch (error) {
		console.error("Error loading profile data:", error);
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

		const modelCatalog = readModelCatalog();
		Object.entries(data.all_models || {}).forEach(([provider, models]) => {
			if (
				Array.isArray(models) &&
				models.length &&
				!getCachedModels(modelCatalog, provider).length
			)
				setCachedModels(modelCatalog, provider, models);
		});
		saveModelCatalog(modelCatalog);

		const providersList = window.VisualRegistry.listProviders();

		providersList.forEach((provObj) => {
			const provider = provObj.id;
			const isCustom = provObj.custom;
			const isActive = provider === data.current_provider;

			const card = document.createElement("div");
			card.className = `provider-card ${isActive ? "active-provider" : ""}`;
			const identityBadge = window.VisualRegistry.renderBadge(provObj);
			const identityMark = window.VisualRegistry.renderLogo(provObj, "small");
			const titleHtml = `${identityMark}<span class="provider-title__name">${provObj.displayName}</span> ${identityBadge} ${isActive ? "<span class='badge-active'>Active</span>" : ""}`;

			let innerHtml = `
				<div class="provider-header" role="button" tabindex="0" aria-expanded="${isActive ? "true" : "false"}">
					<h3 class="provider-title">${titleHtml}</h3>
					<span class="provider-toggle-icon" aria-hidden="true">${isActive ? "▼" : "▲"}</span>
				</div>
				<div class="provider-body ${isActive ? "is-expanded" : ""}">
					<div class="form-group">
						<label for="key-${provider}">API Key (Saved in browser)</label>
						<div class="provider-input-row">
							<input type="password" id="key-${provider}" class="provider-flex-input" placeholder="sk-..." value="${byok[provider]?.api_key || ""}">
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
						<div class="provider-input-row">
							<select id="model-${provider}" class="form-select provider-flex-input">
`;

			const modelsForThisProv = getCachedModels(modelCatalog, provider).slice();
			if (modelsForThisProv.length > 0) {
				if (
					isActive &&
					data.current_model &&
					!modelsForThisProv.includes(data.current_model)
				) {
					modelsForThisProv.unshift(data.current_model);
				}
				modelsForThisProv.forEach((m) => {
					const selected =
						isActive && m === data.current_model ? "selected" : "";
					innerHtml += `<option value="${m}" ${selected}>${m}</option>`;
				});
			} else {
				if (isActive && data.current_model) {
					innerHtml += `<option value="${data.current_model}" selected>${data.current_model}</option>`;
				} else {
					innerHtml += `<option value="">Fetch models first...</option>`;
				}
			}

			innerHtml += `
							</select>
							<button class="btn btn-info btn-sm fetch-models-btn" type="button" data-provider="${provider}">Refresh Models</button>
						</div>
					</div>
					<div class="config-actions provider-actions">
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
				const isExpanded = body.classList.contains("is-expanded");
				body.classList.toggle("is-expanded", !isExpanded);
				header.setAttribute("aria-expanded", String(!isExpanded));
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

function readModelCatalog() {
	try {
		const raw = localStorage.getItem(PROVIDER_MODELS_CACHE_KEY);
		const parsed = raw ? JSON.parse(raw) : {};
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}

function saveModelCatalog(catalog) {
	localStorage.setItem(PROVIDER_MODELS_CACHE_KEY, JSON.stringify(catalog));
}

function getCachedModels(catalog, provider) {
	const entry = catalog[provider];
	if (Array.isArray(entry)) return entry;
	if (!entry || !Array.isArray(entry.models)) return [];
	if (
		entry.fetchedAt &&
		Date.now() - entry.fetchedAt > PROVIDER_MODELS_CACHE_TTL_MS
	)
		return [];
	return entry.models;
}

function setCachedModels(catalog, provider, models) {
	catalog[provider] = { models, fetchedAt: Date.now() };
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
			const previous = select?.value || "";
			const catalog = readModelCatalog();
			const models = [...new Set(data.models.filter(Boolean))];
			setCachedModels(catalog, provider, models);
			saveModelCatalog(catalog);
			if (select) {
				select.innerHTML = "";
				const list = models.slice();
				if (previous && !list.includes(previous)) list.unshift(previous);
				list.forEach((model) => {
					const opt = document.createElement("option");
					opt.value = model;
					opt.textContent = model;
					if (model === previous) opt.selected = true;
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

	const knowledgeForm = document.getElementById("global-knowledge-form");
	if (knowledgeForm)
		knowledgeForm.addEventListener("submit", saveKnowledgeEntry);
	const cancelKnowledgeEdit = document.getElementById("cancel-knowledge-edit");
	if (cancelKnowledgeEdit)
		cancelKnowledgeEdit.addEventListener("click", resetKnowledgeForm);

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
				window.toggleSidebar();
			}
		}
	});

	const tempSlider = document.getElementById("adv-temperature");
	if (tempSlider) {
		tempSlider.addEventListener("input", (e) => {
			const out = document.getElementById("val-temperature");
			if (out) out.textContent = parseFloat(e.target.value).toFixed(1);
		});
		attachSliderGuard(tempSlider);
	}

	const topPSlider = document.getElementById("adv-top-p");
	if (topPSlider) {
		topPSlider.addEventListener("input", (e) => {
			const out = document.getElementById("val-top-p");
			if (out) out.textContent = parseFloat(e.target.value).toFixed(2);
		});
		attachSliderGuard(topPSlider);
	}

	const topKSlider = document.getElementById("adv-top-k");
	if (topKSlider) {
		topKSlider.addEventListener("input", (e) => {
			const out = document.getElementById("val-top-k");
			if (out) out.textContent = parseInt(e.target.value, 10).toString();
		});
		attachSliderGuard(topKSlider);
	}

	const saveAdvancedBtn = document.getElementById("save-advanced-settings");
	if (saveAdvancedBtn)
		saveAdvancedBtn.addEventListener("click", saveAdvancedSettings);

	const saveImageModelBtn = document.getElementById("save-image-model");
	if (saveImageModelBtn)
		saveImageModelBtn.addEventListener("click", saveImageModel);

	const clearChatHistoryBtn = document.getElementById("clear-chat-history");
	if (clearChatHistoryBtn)
		clearChatHistoryBtn.addEventListener("click", clearChatHistory);

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
	const personaPreset = getValueIfExists("persona-preset", "helpful");
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
	setValueIfExists("adv-top-k", source.top_k ?? 40);
	setValueIfExists("adv-max-tokens", source.max_tokens ?? 4096);
	setValueIfExists("adv-history-limit", source.history_limit ?? 20);
	setValueIfExists(
		"adv-additional-instructions",
		source.additional_instructions ?? "",
	);
	const reasoning = document.getElementById("adv-reasoning");
	if (reasoning) reasoning.checked = Boolean(source.enable_reasoning);
	const vision = document.getElementById("adv-vision");
	if (vision) vision.checked = Boolean(source.enable_vision);
	const tempOut = document.getElementById("val-temperature");
	if (tempOut)
		tempOut.textContent = Number(source.temperature ?? 1.0).toFixed(1);
	const topPOut = document.getElementById("val-top-p");
	if (topPOut) topPOut.textContent = Number(source.top_p ?? 1.0).toFixed(2);
	const topKOut = document.getElementById("val-top-k");
	if (topKOut) topKOut.textContent = String(source.top_k ?? 40);
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
			top_k: getNumberIfExists("adv-top-k", 40),
			max_tokens: getNumberIfExists("adv-max-tokens", 4096),
			history_limit: getNumberIfExists("adv-history-limit", 20),
			enable_reasoning: getCheckedIfExists("adv-reasoning"),
			enable_vision: getCheckedIfExists("adv-vision"),
			additional_instructions: getValueIfExists(
				"adv-additional-instructions",
				"",
			),
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
			btn.classList.add("is-saved");
			setTimeout(() => {
				btn.textContent = original;
				btn.classList.remove("is-saved");
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
	if (baseGroup) baseGroup.classList.toggle("is-visible", showConditional);
	if (modelGroup) modelGroup.classList.toggle("is-visible", showConditional);
}

window.saveBYOKConfig = saveBYOKConfig;

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
				entry.target.classList.add("is-visible");
			}
		});
	}, observerOptions);

	document.querySelectorAll(".config-section").forEach((section) => {
		section.classList.add("animate-on-scroll");
		observer.observe(section);
	});

	console.log("Config animations initialized");
}

// Make functions globally available
window.showSuccess = showSuccess;
window.showError = showError;
window.toggleSidebar = window.toggleSidebar || (() => {});

async function loadLocation() {
	try {
		const response = await fetch("/api/profile");
		if (!response.ok) return;
		const data = await response.json();
		const profile = data.profile || data;
		setValueIfExists("location-lat", profile.location_lat ?? "");
		setValueIfExists("location-lon", profile.location_lon ?? "");
	} catch (e) {
		console.error("Failed to load location:", e);
	}
}

async function saveLocation() {
	const lat = Number.parseFloat(getValueIfExists("location-lat", ""));
	const lon = Number.parseFloat(getValueIfExists("location-lon", ""));
	if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
		showError("Enter both latitude and longitude before saving.");
		return;
	}

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

// Export to window for inline onclick handlers
window.useCurrentLocation = _useCurrentLocation;

// Load vision model on page load
document.addEventListener("DOMContentLoaded", loadVisionModel);

// Export to window to fix unused variable warnings from HTML onclicks
window.clearChatHistory = clearChatHistory;
window.saveImageModel = saveImageModel;
window.saveLocation = saveLocation;
window.setProviderActive = setProviderActive;
window.testProviderConnection = testProviderConnection;
window.toggleBYOKFields = toggleBYOKFields;
window.updateModelDropdown = updateModelDropdown;

// ── Slider drag-guard ────────────────────────────────────────────────────
// Range inputs in this UI were firing during vertical page scroll
// (the thumb follows a tiny accidental horizontal jitter). This guard
// requires the pointer to commit to a *predominantly horizontal* drag
// before the slider starts emitting "input" events, and suppresses
// value changes from a near-vertical gesture.
//
// Behaviour:
//   1. On pointerdown, snapshot the pointer position and the slider
//      value, and capture the pointer so the page cannot scroll while
//      we are deciding.
//   2. Mark the gesture as "armed" only after |dx| > 6px AND
//      |dx| > |dy| * 1.4. Until then we do nothing — vertical scroll
//      wins, the slider value is unchanged.
//   3. While armed, map horizontal drag to step-multiple value changes
//      so the user sees a real change once they commit horizontally.
//   4. On pointerup, if the gesture never armed, restore the original
//      value (no accidental change persists).
function attachSliderGuard(slider) {
	if (!slider) return;
	const ARM_THRESHOLD_PX = 6;
	const HORIZONTAL_BIAS = 1.4;
	let startX = 0;
	let startY = 0;
	let startValue = 0;
	let pointerId = -1;
	let armed = false;

	const step = parseFloat(slider.getAttribute("step")) || 1;
	const min = parseFloat(slider.getAttribute("min")) || 0;
	const max = parseFloat(slider.getAttribute("max")) || 100;
	const clamp = (v) => Math.min(max, Math.max(min, v));

	const onDown = (e) => {
		if (e.pointerType === "mouse" && e.button !== 0) return;
		pointerId = e.pointerId;
		startX = e.clientX;
		startY = e.clientY;
		startValue = parseFloat(slider.value);
		armed = false;
		try {
			slider.setPointerCapture(pointerId);
		} catch (_err) {
			// Capture can fail on some browsers — fall through, native
			// behaviour is still acceptable.
		}
	};

	const onMove = (e) => {
		if (e.pointerId !== pointerId) return;
		const dx = e.clientX - startX;
		const dy = e.clientY - startY;
		if (!armed) {
			if (
				Math.abs(dx) > ARM_THRESHOLD_PX &&
				Math.abs(dx) > Math.abs(dy) * HORIZONTAL_BIAS
			) {
				armed = true;
			} else {
				return; // still a vertical scroll — do nothing
			}
		}
		const rect = slider.getBoundingClientRect();
		const width = Math.max(1, rect.width);
		const pxPerUnit = width / (max - min || 1);
		const deltaUnits = dx / pxPerUnit;
		const newValue = clamp(startValue + Math.round(deltaUnits / step) * step);
		if (parseFloat(slider.value) !== newValue) {
			slider.value = String(newValue);
			slider.dispatchEvent(new Event("input", { bubbles: true }));
		}
		e.preventDefault();
	};

	const onUp = (e) => {
		if (e.pointerId !== pointerId) return;
		try {
			slider.releasePointerCapture(pointerId);
		} catch (_err) {
			// Already released — ignore.
		}
		if (!armed) {
			// Vertical scroll never armed: revert any visual drift and
			// emit no change.
			slider.value = String(startValue);
		}
		armed = false;
		pointerId = -1;
	};

	slider.addEventListener("pointerdown", onDown);
	slider.addEventListener("pointermove", onMove);
	slider.addEventListener("pointerup", onUp);
	slider.addEventListener("pointercancel", onUp);
}

async function loadGlobalKnowledge() {
	const list = document.getElementById("global-knowledge-list");
	if (!list) return;
	try {
		const response = await fetch("/api/global-knowledge", {
			headers: { Accept: "application/json" },
		});
		if (!response.ok) throw new Error("Failed to load Global Knowledge");
		const data = await response.json();
		renderGlobalKnowledge(data.entries || []);
	} catch (error) {
		setKnowledgeStatus(error.message, true);
	}
}

function renderGlobalKnowledge(entries) {
	const list = document.getElementById("global-knowledge-list");
	if (!list) return;
	list.replaceChildren();
	if (entries.length === 0) {
		const empty = document.createElement("p");
		empty.className = "form-hint";
		empty.textContent = "No explicit knowledge entries yet.";
		list.appendChild(empty);
		return;
	}
	entries.forEach((entry) => {
		const item = document.createElement("article");
		item.className = `knowledge-entry ${entry.enabled ? "" : "knowledge-entry-disabled"}`;
		item.dataset.entryId = entry.id;
		const header = document.createElement("div");
		header.className = "knowledge-entry-header";
		const title = document.createElement("strong");
		title.textContent = entry.category || "General";
		header.appendChild(title);
		const actions = document.createElement("div");
		const edit = document.createElement("button");
		edit.type = "button";
		edit.className = "btn btn-secondary btn-sm";
		edit.textContent = "Edit";
		edit.addEventListener("click", () => editKnowledgeEntry(entry));
		const remove = document.createElement("button");
		remove.type = "button";
		remove.className = "btn btn-danger btn-sm";
		remove.textContent = "Delete";
		remove.addEventListener("click", () => deleteKnowledgeEntry(entry.id));
		actions.append(edit, remove);
		header.appendChild(actions);
		const content = document.createElement("p");
		content.textContent = entry.content;
		item.append(header, content);
		list.appendChild(item);
	});
}

function editKnowledgeEntry(entry) {
	setValueIfExists("knowledge-entry-id", entry.id);
	setValueIfExists("knowledge-entry-sort-order", entry.sort_order ?? 0);
	setValueIfExists("knowledge-category", entry.category);
	setValueIfExists("knowledge-content", entry.content);
	const enabled = document.getElementById("knowledge-enabled");
	if (enabled) enabled.checked = entry.enabled;
	setTextIfExists("save-knowledge-entry", "Save entry");
	const cancel = document.getElementById("cancel-knowledge-edit");
	if (cancel) cancel.hidden = false;
	document.getElementById("knowledge-category")?.focus();
}

function resetKnowledgeForm() {
	document.getElementById("global-knowledge-form")?.reset();
	const sortOrder = document.getElementById("knowledge-entry-sort-order");
	if (sortOrder) sortOrder.value = "0";
	const id = document.getElementById("knowledge-entry-id");
	if (id) id.value = "";
	setTextIfExists("save-knowledge-entry", "Add entry");
	const cancel = document.getElementById("cancel-knowledge-edit");
	if (cancel) cancel.hidden = true;
}

async function saveKnowledgeEntry(event) {
	event.preventDefault();
	const id = getValueIfExists("knowledge-entry-id");
	const payload = {
		category: getValueIfExists("knowledge-category").trim() || "General",
		content: getValueIfExists("knowledge-content").trim(),
		enabled: getCheckedIfExists("knowledge-enabled"),
		sort_order:
			Number.parseInt(
				getValueIfExists("knowledge-entry-sort-order", "0"),
				10,
			) || 0,
	};
	if (!payload.content) {
		setKnowledgeStatus("Content is required.", true);
		return;
	}
	try {
		const response = await fetch(
			id
				? `/api/global-knowledge/${encodeURIComponent(id)}`
				: "/api/global-knowledge",
			{
				method: id ? "PATCH" : "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify(payload),
			},
		);
		if (!response.ok) throw new Error("Failed to save Global Knowledge entry");
		resetKnowledgeForm();
		await loadGlobalKnowledge();
		setKnowledgeStatus("Global Knowledge saved.");
	} catch (error) {
		setKnowledgeStatus(error.message, true);
	}
}

async function deleteKnowledgeEntry(id) {
	if (!window.confirm("Delete this Global Knowledge entry?")) return;
	try {
		const response = await fetch(
			`/api/global-knowledge/${encodeURIComponent(id)}`,
			{ method: "DELETE", headers: { Accept: "application/json" } },
		);
		if (!response.ok)
			throw new Error("Failed to delete Global Knowledge entry");
		await loadGlobalKnowledge();
		setKnowledgeStatus("Global Knowledge entry deleted.");
	} catch (error) {
		setKnowledgeStatus(error.message, true);
	}
}

function setKnowledgeStatus(message, isError = false) {
	const status = document.getElementById("knowledge-status");
	if (status) {
		status.textContent = message;
		status.classList.toggle("status-error", isError);
	}
}
