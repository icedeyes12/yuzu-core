// Ported from static/js/config.js: provider/model discovery, BYOK key storage,
// profile/advanced/image-model/location forms, and Global Knowledge CRUD.
// Differences from the Jinja version: fetch -> apiFetch (session cookie, BYOK
// header, 401 auth gate) and the provider_models cache key resolves lazily
// after /api/v1/auth/me establishes the user-scoped storage namespace.

import { toggleSidebar } from "../components/sidebar.js";
import { bootApp } from "../main.js";
import { apiFetch } from "../modules/apiFetch.js";
import { render as renderBadge } from "../modules/badge-registry.js";
import {
	encodeByokConfig,
	getByokConfig,
	getByokProvider,
	getUserStorageKey,
	maskApiKey,
	writeByokConfig,
} from "../modules/clientStorage.js";
import { listProviders } from "../modules/provider-registry.js";
import { escapeHtml } from "../modules/tool-renderer/dom-utils.js";
import { renderLogo } from "../modules/visual-registry.js";

// Global config state (populated from /api/v1/config)
let appConfig = null;

const maskedProviderKeys = new WeakMap();

function getProviderModelsCacheKey() {
	return getUserStorageKey("provider_models");
}

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
	if (raw.trim() === "") return fallback;
	const num = Number(raw);
	return Number.isFinite(num) ? num : fallback;
}

function getActiveModelInfo() {
	const provider =
		appConfig?.current_provider || appConfig?.ai_providers?.current_provider;
	const model =
		appConfig?.current_model || appConfig?.ai_providers?.current_model;
	return (
		(appConfig?.model_infos?.[provider] || []).find(
			(info) => info.id === model,
		) || null
	);
}

function setActiveConfig(provider, model) {
	if (!appConfig) return;
	appConfig.current_provider = provider;
	appConfig.current_model = model;
	if (appConfig.ai_providers) {
		appConfig.ai_providers.current_provider = provider;
		appConfig.ai_providers.current_model = model;
	}
}

function getModelInfo(provider, model) {
	return (
		(appConfig?.model_infos?.[provider] || []).find(
			(info) => info.id === model,
		) || null
	);
}

function capabilityMark(value) {
	return value === "supported" ? "✓" : value === "unsupported" ? "—" : "?";
}

function renderCapabilitySummary(info) {
	const capabilities = info?.capabilities || {};
	const reasoning = capabilities.reasoning?.mode || "unknown";
	const limits = info?.limits || {};
	const value = (name, state) =>
		`<span class="model-capability-summary__item"><span class="model-capability-summary__state" aria-label="${state}">${capabilityMark(state)}</span> ${name}</span>`;
	const limit = (name, number) =>
		`<span class="model-capability-summary__item">${name}: ${Number.isInteger(number) ? number.toLocaleString() : "?"}</span>`;

	if (!info) {
		return '<span class="model-capability-summary__title">Model capabilities: ?</span>';
	}
	return [
		`<span class="model-capability-summary__title">${info.id} capabilities</span>`,
		value("Vision", capabilities.vision),
		value("Tools", capabilities.function_call),
		value("Structured output", capabilities.structured_output),
		value(
			"Reasoning",
			reasoning === "unknown"
				? "unknown"
				: reasoning === "unsupported"
					? "unsupported"
					: "supported",
		),
		value("Image generation", capabilities.image_generation),
		limit("Context", limits.context_window),
		limit("Max output", limits.max_output_tokens),
	].join("");
}

function updateCapabilitySummary(provider, model, target) {
	if (target)
		target.innerHTML = renderCapabilitySummary(getModelInfo(provider, model));
	const activeProvider =
		appConfig?.current_provider || appConfig?.ai_providers?.current_provider;
	const activeModel =
		appConfig?.current_model || appConfig?.ai_providers?.current_model;
	const active = document.getElementById("active-model-capabilities");
	if (active && provider === activeProvider && model === activeModel) {
		active.innerHTML = renderCapabilitySummary(getModelInfo(provider, model));
	}
}

/**
 * Updates reasoning and vision controls to reflect the active model's capabilities.
 */
function applyActiveModelCapabilities() {
	const capabilities = getActiveModelInfo()?.capabilities || {};
	const reasoning = capabilities.reasoning || {};
	const reasoningControl = document.getElementById("adv-reasoning");
	const visionControl = document.getElementById("adv-vision");
	if (reasoningControl) {
		reasoningControl.disabled = reasoning.mode === "unsupported";
		if (reasoningControl.disabled) reasoningControl.checked = false;
	}
	if (visionControl) {
		visionControl.disabled = capabilities.vision === "unsupported";
		if (visionControl.disabled) visionControl.checked = false;
	}
}

/**
 * Selects the available source for a profile's advanced settings.
 * @param {Object} data - Profile data containing advanced or profile settings.
 * @return {Object} The advanced settings, profile settings, original data, or an empty object, in that order of preference.
 */
function getProfileAdvancedSource(data) {
	return data?.advanced || data?.profile || data || {};
}

/**
 * Validates an API key for a provider.
 * @param {string} provider - The provider identifier.
 * @param {string} value - The API key to validate.
 * @return {string|null} An error message when the key is invalid, or `null` when it is valid.
 */
function validateProviderKey(provider, value) {
	if (provider === "custom_openai" || provider === "custom_anthropic")
		return null;
	if (!value) return "API key cannot be empty.";
	if (value.length < 8)
		return "The API key appears to be incomplete or invalid.";
	if (/\.\.\.|\*\*\*|•••/.test(value)) {
		return "The entered value looks like a masked API key.";
	}
	return null;
}

/**
 * Initializes the configuration page after authentication and configuration loading succeed.
 */
async function init() {
	const me = await bootApp({ page: "config" });
	if (!me) return;
	console.log("Config page loaded - initializing...");
	const loaded = await loadAppConfig();
	if (!loaded) return;
	await Promise.all([loadGlobalKnowledge(), loadProviderSettings()]);
	setupEventListeners();
	initializeConfigAnimations();
}

// Load application configuration from backend (SSOT)
async function loadAppConfig() {
	try {
		const response = await apiFetch("/api/v1/config", {
			headers: { Accept: "application/json" },
		});
		const data = await readJsonResponse(response);
		if (!response.ok || data.status !== "success") {
			throw new Error(getApiError(data, response.status));
		}
		appConfig = data;
		const profile = appConfig.profile || {};
		loadProfileDataFromConfig(profile);
		loadAdvancedSettingsFromData(profile);
		loadImageModelFromConfig();
		return true;
	} catch (error) {
		console.error("Error loading app config:", error);
		showError(`Could not load settings: ${error.message}`);
		return false;
	}
}

async function readJsonResponse(response) {
	const text = await response.text();
	try {
		return text ? JSON.parse(text) : {};
	} catch {
		throw new Error(`Server returned an invalid response (${response.status})`);
	}
}

function getApiError(data, status) {
	return data?.detail || data?.message || `Request failed (${status})`;
}

// Load profile data for editable application settings
function loadProfileDataFromConfig(data) {
	setTextIfExists("affection-value", data.affection);
	setValueIfExists("affection-level", data.affection);
	setValueIfExists("display-name", data.user_name || "");
	setValueIfExists("partner-name", data.partner_name || "");
	setValueIfExists("personality-preset", data.personality_preset || "helpful");
	setValueIfExists("personality-custom", data.personality_custom || "");
	setValueIfExists("character-profile", data.character_profile || "");
	updateCustomPersonalityVisibility();
	setValueIfExists("location-lat", data.location_lat ?? "");
	setValueIfExists("location-lon", data.location_lon ?? "");
}

function updateCustomPersonalityVisibility() {
	const preset = getValueIfExists("personality-preset", "helpful");
	const group = document.getElementById("custom-personality-group");
	if (group) group.hidden = preset !== "custom";
}

async function loadProfileData() {
	if (appConfig?.profile) {
		loadProfileDataFromConfig(appConfig.profile);
		return appConfig.profile;
	}
	await loadAppConfig();
	return appConfig?.profile || null;
}

// Load provider settings
async function loadProviderSettings() {
	try {
		if (!appConfig?.ai_providers) {
			throw new Error("Provider configuration is missing");
		}
		const data = {
			...appConfig.ai_providers,
			all_models: appConfig.all_models || appConfig.ai_providers.all_models,
			current_provider:
				appConfig.current_provider || appConfig.ai_providers.current_provider,
			current_model:
				appConfig.current_model || appConfig.ai_providers.current_model,
			status: "success",
		};
		const grid = document.getElementById("providers-grid");
		if (!grid) return;
		grid.innerHTML = "";

		setTextIfExists(
			"current-provider",
			data.current_provider && data.current_model
				? `${data.current_provider}/${data.current_model}`
				: data.current_provider || "Not set",
		);

		const modelCatalog = readModelCatalog();
		Object.entries(data.all_models || {}).forEach(([provider, models]) => {
			if (!Array.isArray(models) || !models.length) return;
			const cached = getCachedModels(modelCatalog, provider);
			if (!cached.length) setCachedModels(modelCatalog, provider, models);
		});
		saveModelCatalog(modelCatalog);

		const providersList = listProviders();

		providersList.forEach((provObj) => {
			const provider = provObj.id;
			const isCustom = provObj.custom;
			const isActive = provider === data.current_provider;
			const providerConfig = getByokProvider(provider);
			const provKey = providerConfig.api_key || "";
			const provUrl = providerConfig.base_url || "";

			const card = document.createElement("div");
			card.className = `provider-card ${isActive ? "active-provider" : ""}`;
			const identityBadge = renderBadge(provObj);
			const identityMark = renderLogo(provObj, "small");
			const titleHtml = `${identityMark}<span class="provider-title__name">${provObj.displayName}</span> ${identityBadge} ${isActive ? "<span class='badge-active'>Active</span>" : ""}`;

			let innerHtml = `
				<div class="provider-header" role="button" tabindex="0" aria-expanded="${isActive ? "true" : "false"}" aria-controls="provider-body-${provider}">
					<h3 class="provider-title">${titleHtml}</h3>
					<span class="provider-toggle-icon" aria-hidden="true">${isActive ? "▼" : "▲"}</span>
				</div>
				<div class="provider-body ${isActive ? "is-expanded" : ""}" id="provider-body-${provider}">
					<div class="form-group">
						<label for="key-${provider}">API Key (Saved in browser)</label>
						<div class="provider-input-row">
							<input type="text" id="key-${provider}" class="provider-flex-input provider-key-input" placeholder="sk-..." autocomplete="off" value="${escapeHtml(maskApiKey(provKey))}">
							<button class="btn btn-secondary btn-sm save-byok-btn" type="button" data-provider="${provider}">Save Key</button>
						</div>
					</div>
`;

			if (isCustom) {
				innerHtml += `
					<div class="form-group">
						<label for="url-${provider}">Base URL</label>
						<input type="text" id="url-${provider}" placeholder="http://localhost:20128/v1" autocomplete="url" value="${provUrl}">
					</div>
				`;
			}

			innerHtml += `
					<div class="form-group">
						<label for="model-${provider}">Model</label>
						<div class="provider-input-row">
							<select id="model-${provider}" class="form-select provider-flex-input">
`;

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
			populateModelSelect(
				card.querySelector(`#model-${provider}`),
				getCachedModels(modelCatalog, provider),
				isActive ? data.current_model || "" : "",
			);
			const modelSelect = card.querySelector(`#model-${provider}`);
			const capabilitySummary = document.createElement("div");
			capabilitySummary.className = "model-capability-summary";
			modelSelect.closest(".form-group")?.appendChild(capabilitySummary);
			updateCapabilitySummary(provider, modelSelect.value, capabilitySummary);
			modelSelect.addEventListener("change", () =>
				updateCapabilitySummary(provider, modelSelect.value, capabilitySummary),
			);
			if (isActive) {
				applyActiveModelCapabilities();
				updateCapabilitySummary(
					provider,
					modelSelect.value,
					document.getElementById("active-model-capabilities"),
				);
			}
			grid.appendChild(card);
			setupMaskedKeyInput(card.querySelector(`#key-${provider}`), provKey);

			// Add accordion toggle
			const header = card.querySelector(".provider-header");
			const body = card.querySelector(".provider-body");
			const icon = header.querySelector(".provider-toggle-icon");

			// Set initial icon
			if (icon) icon.textContent = isActive ? "▲" : "▼";

			const toggleProvider = () => {
				const isExpanded = body.classList.contains("is-expanded");
				body.classList.toggle("is-expanded", !isExpanded);
				header.setAttribute("aria-expanded", String(!isExpanded));
				if (icon) icon.textContent = isExpanded ? "▼" : "▲";
			};

			header.addEventListener("click", toggleProvider);
			header.addEventListener("keydown", (event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					toggleProvider();
				}
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

function saveBYOKForProvider(provider, notify = true) {
	const keyInput = document.getElementById(`key-${provider}`);
	if (!keyInput) return false;

	const displayedValue = keyInput.value.trim();
	const storedKey = maskedProviderKeys.get(keyInput) || "";
	const key =
		displayedValue === maskApiKey(storedKey) ? storedKey : displayedValue;
	const validationError = validateProviderKey(provider, key);
	if (validationError) {
		showError(validationError);
		return false;
	}

	const byok = getByokConfig();
	const providerConfig = getByokProvider(provider);
	providerConfig.api_key = key;
	maskedProviderKeys.set(keyInput, key);
	keyInput.value = maskApiKey(key);

	if (provider === "yuzu_portal") {
		delete providerConfig.base_url;
	} else if (provider.startsWith("custom")) {
		const baseInput = document.getElementById(`url-${provider}`);
		providerConfig.base_url = baseInput?.value.trim() || "";
	}

	byok.providers[provider] = providerConfig;
	if (!writeByokConfig(byok)) {
		showError("User scope is unavailable; provider key was not saved.");
		return false;
	}
	if (notify) showSuccess(`${provider} key saved in browser.`);
	updateImageModelWarning(getValueIfExists("image-model"));
	return true;
}

function setupMaskedKeyInput(input, storedKey) {
	if (!input) return;
	maskedProviderKeys.set(input, storedKey);
	input.addEventListener("focus", () => {
		input.select();
	});
}

function readModelCatalog() {
	const key = getProviderModelsCacheKey();
	if (!key) return {};
	try {
		const raw = localStorage.getItem(key);
		const parsed = raw ? JSON.parse(raw) : {};
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}

function saveModelCatalog(catalog) {
	const key = getProviderModelsCacheKey();
	if (key) {
		localStorage.setItem(key, JSON.stringify(catalog));
	}
}

function getCachedModels(catalog, provider) {
	const entry = catalog[provider];
	if (Array.isArray(entry)) return entry;
	if (!entry || !Array.isArray(entry.models)) return [];
	return entry.models.filter((model) => typeof model === "string" && model);
}

function setCachedModels(catalog, provider, models) {
	catalog[provider] = {
		models: [
			...new Set(models.filter((model) => typeof model === "string" && model)),
		],
		fetchedAt: Date.now(),
	};
}
function populateModelSelect(select, models, currentModel = "") {
	if (!select) return;
	select.replaceChildren();
	const options = [
		...new Set(models.filter((model) => typeof model === "string" && model)),
	];
	if (currentModel && !options.includes(currentModel))
		options.unshift(currentModel);
	if (options.length === 0) {
		const empty = document.createElement("option");
		empty.value = "";
		empty.textContent = "Refresh models to choose one";
		select.appendChild(empty);
		return;
	}
	options.forEach((model) => {
		const option = document.createElement("option");
		option.value = model;
		option.textContent = model;
		option.selected = model === currentModel;
		select.appendChild(option);
	});
}

function invalidateModelCache(provider) {
	const catalog = readModelCatalog();
	delete catalog[provider];
	saveModelCatalog(catalog);
	if (appConfig?.model_infos) delete appConfig.model_infos[provider];
	const select = document.getElementById(`model-${provider}`);
	if (select) populateModelSelect(select, [], "");
	if (appConfig?.current_provider === provider) {
		appConfig.current_model = "";
		if (appConfig.ai_providers) appConfig.ai_providers.current_model = "";
		const active = document.getElementById("active-model-capabilities");
		if (active) active.innerHTML = renderCapabilitySummary(null);
		applyActiveModelCapabilities();
	}
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
		const provConfig = getByokProvider(provider);

		const headers = {};
		if (provConfig.api_key) headers["X-Provider-Key"] = provConfig.api_key;
		if (provConfig.base_url)
			headers["X-Provider-BaseUrl"] = provConfig.base_url;

		const response = await apiFetch(
			`/api/v1/proxy/models/${provider}/refresh`,
			{
				method: "POST",
				headers: { ...headers, Accept: "application/json" },
			},
		);
		const data = await readJsonResponse(response);

		if (!response.ok || data.status !== "success") {
			invalidateModelCache(provider);
			throw new Error(getApiError(data, response.status));
		}

		if (data.models) {
			const select = document.getElementById(`model-${provider}`);
			const previous = select?.value || "";
			const catalog = readModelCatalog();
			const models = [...new Set(data.models.filter(Boolean))];
			setCachedModels(catalog, provider, models);
			saveModelCatalog(catalog);
			if (select) populateModelSelect(select, models, previous);
			if (Array.isArray(data.model_infos)) {
				appConfig.model_infos = appConfig.model_infos || {};
				appConfig.model_infos[provider] = data.model_infos;
				const modelSelect = document.getElementById(`model-${provider}`);
				const summary = modelSelect
					?.closest(".form-group")
					?.querySelector(".model-capability-summary");
				updateCapabilitySummary(provider, modelSelect?.value || "", summary);
				applyActiveModelCapabilities();
				if (provider === appConfig.current_provider) {
					updateCapabilitySummary(
						provider,
						appConfig.current_model,
						document.getElementById("active-model-capabilities"),
					);
				}
			}
			showSuccess(`Models loaded for ${provider}.`);
		} else {
			showError(`Failed to fetch models: ${data.message || "Unknown error"}`);
		}
	} catch (err) {
		console.error(err);
		showError(`Could not refresh ${provider} models: ${err.message}`);
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.textContent = "Refresh Models";
		}
	}
}

// Test provider connection
async function testProviderConnection(providerName) {
	if (!saveBYOKForProvider(providerName, false)) return;
	const statusElement = document.getElementById("connection-status");
	if (!statusElement) return;
	statusElement.textContent = "Testing...";
	statusElement.className = "status-checking";
	statusElement.classList.add("pulse");

	try {
		const headers = { "Content-Type": "application/json" };
		try {
			const encoded = encodeByokConfig();
			if (encoded) headers["X-BYOK-Config"] = encoded;
		} catch (e) {
			console.warn("Error attaching BYOK config for test:", e);
		}

		const response = await apiFetch("/api/v1/providers/test_connection", {
			method: "POST",
			headers: headers,
			body: JSON.stringify({ provider_name: providerName }),
		});

		const result = await readJsonResponse(response);
		statusElement.classList.remove("pulse");

		if (!response.ok || result.status !== "success") {
			throw new Error(getApiError(result, response.status));
		}

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
	} catch (error) {
		console.error("Error testing provider connection:", error);
		statusElement.classList.remove("pulse");
		statusElement.textContent = "Test error";
		statusElement.className = "status-disconnected";
		showError(`Could not test ${providerName}: ${error.message}`);
	}
}

function setupEventListeners() {
	console.log("Setting up config event listeners...");

	const saveProfileBtn = document.getElementById("save-profile");
	if (saveProfileBtn)
		saveProfileBtn.addEventListener("click", saveProfileSettings);

	const personalityPreset = document.getElementById("personality-preset");
	if (personalityPreset) {
		personalityPreset.addEventListener(
			"change",
			updateCustomPersonalityVisibility,
		);
	}

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

	const useCurrentLocationBtn = document.getElementById("use-current-location");
	if (useCurrentLocationBtn)
		useCurrentLocationBtn.addEventListener("click", _useCurrentLocation);

	document.addEventListener("click", (event) => {
		const dismiss = event.target.closest(
			'[data-action="dismiss-notification"]',
		);
		if (dismiss) dismiss.closest(".config-notification")?.remove();
	});

	console.log("Event listeners setup complete");
}

// Load image model on page load
const IMAGE_MODEL_OPTIONS = Object.freeze([
	{ value: "", label: "Not configured", provider: "" },
	{
		value: "z-image-turbo",
		label: "Z-Image Turbo",
		provider: "chutes",
		key: "Chutes Key",
	},
	{
		value: "qwen-image",
		label: "Qwen Image",
		provider: "chutes",
		key: "Chutes Key",
	},
	{
		value: "qwen-image-edit",
		label: "Qwen Image Edit",
		provider: "chutes",
		key: "Chutes Key",
	},
	{
		value: "ag/gemini-3.1-flash-image",
		label: "Gemini 3.1 Flash Image",
		provider: "yuzu_portal",
		key: "Yuzu Key",
	},
	{
		value: "gemini/gemini-2.5-flash-image",
		label: "Gemini 2.5 Flash Image",
		provider: "yuzu_portal",
		key: "Yuzu Key",
	},
]);

function isImageModelKeyConfigured(option) {
	if (!option?.provider) return true;
	return Boolean(getByokProvider(option.provider).api_key?.trim());
}

function updateImageModelWarning(model) {
	const warning = document.getElementById("image-model-warning");
	const saveButton = document.getElementById("save-image-model");
	if (!warning) return true;

	const selected = IMAGE_MODEL_OPTIONS.find((option) => option.value === model);
	const requiresKey = Boolean(selected?.key);
	const configured = !requiresKey || isImageModelKeyConfigured(selected);

	warning.classList.toggle("image-model-warning", requiresKey && !configured);
	warning.classList.toggle("image-model-configured", requiresKey && configured);
	warning.hidden = !requiresKey;
	warning.textContent = !requiresKey
		? ""
		: configured
			? `✓ ${selected.key} is configured.`
			: `⚠️ Warning: You have not set up the ${selected.key}. Please configure it in the provider list above to use this model.`;

	if (saveButton) saveButton.disabled = requiresKey && !configured;
	return configured;
}

function loadImageModelFromConfig() {
	const imageModel = String(appConfig?.profile?.image_model || "").trim();
	const selectedModel = IMAGE_MODEL_OPTIONS.some(
		(option) => option.value === imageModel,
	)
		? imageModel
		: "";
	const select = document.getElementById("image-model");
	if (select) {
		select.innerHTML = IMAGE_MODEL_OPTIONS.map(
			(option) => `<option value="${option.value}">${option.label}</option>`,
		).join("");
		select.value = selectedModel;
		updateImageModelWarning(selectedModel);
		select.addEventListener("change", () =>
			updateImageModelWarning(select.value),
		);
	}
	setTextIfExists("current-image-model", selectedModel || "Not configured");
	updateImageModelWarning(selectedModel);
}

// Save image model setting
async function saveImageModel() {
	if (!document.getElementById("image-model")) return;

	const btn = document.getElementById("save-image-model");
	if (!btn) return;

	const imageModel = getValueIfExists("image-model", "").trim() || null;
	const selected = IMAGE_MODEL_OPTIONS.find(
		(option) => option.value === imageModel,
	);
	if (selected?.key && !isImageModelKeyConfigured(selected)) {
		updateImageModelWarning(imageModel);
		showError(`Configure the ${selected.key} before saving this image model.`);
		return;
	}

	const originalText = btn.textContent;
	btn.textContent = "Saving...";
	btn.disabled = true;

	try {
		const updates = { image_model: imageModel };
		const response = await apiFetch("/api/v1/update_profile", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ updates }),
		});
		const result = await readJsonResponse(response);
		if (!response.ok || result.status !== "success") {
			throw new Error(getApiError(result, response.status));
		}
		Object.assign(appConfig.profile, updates);
		setTextIfExists("current-image-model", imageModel || "Not configured");
		updateImageModelWarning(imageModel);
		showSuccess("Image model saved successfully!");
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
		const response = await apiFetch("/api/v1/providers/set_preferred", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
			},
			body: JSON.stringify({
				provider_name: providerName,
				model_name: modelName,
			}),
		});

		const result = await readJsonResponse(response);

		if (response.ok && result.status === "success") {
			setActiveConfig(providerName, modelName);
			updateCapabilitySummary(
				providerName,
				modelName,
				document.getElementById("active-model-capabilities"),
			);
			applyActiveModelCapabilities();
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
			showError(
				`Could not set active provider: ${getApiError(result, response.status)}`,
			);
		}
	} catch (error) {
		console.error("Error setting active provider:", error);
		showError(`Could not set active provider: ${error.message}`);
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
	const personalityPreset = getValueIfExists("personality-preset", "helpful");
	const personalityCustom = getValueIfExists("personality-custom", "");
	const characterProfile = getValueIfExists("character-profile", "");

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
		const response = await apiFetch("/api/v1/update_profile", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				updates: {
					user_name: displayName,
					partner_name: partnerName,
					affection: parseInt(affection, 10),
					personality_preset: personalityPreset,
					personality_custom: personalityCustom,
					character_profile: characterProfile,
				},
			}),
		});
		const result = await readJsonResponse(response);
		if (!response.ok || result.status !== "success") {
			throw new Error(getApiError(result, response.status));
		}
		Object.assign(appConfig.profile, {
			user_name: displayName,
			partner_name: partnerName,
			affection: parseInt(affection, 10),
			personality_preset: personalityPreset,
			personality_custom: personalityCustom,
			character_profile: characterProfile,
		});
		showSuccess("Profile settings saved successfully!");
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
	setValueIfExists("adv-temperature", source.temperature);
	setValueIfExists("adv-top-p", source.top_p);
	setValueIfExists("adv-top-k", source.top_k);
	setValueIfExists("adv-max-tokens", source.max_tokens);
	setValueIfExists("adv-history-limit", source.history_limit);
	setValueIfExists(
		"adv-additional-instructions",
		source.additional_instructions || "",
	);
	const reasoning = document.getElementById("adv-reasoning");
	if (reasoning) reasoning.checked = Boolean(source.enable_reasoning);
	const vision = document.getElementById("adv-vision");
	if (vision) vision.checked = Boolean(source.enable_vision);
	const tempOut = document.getElementById("val-temperature");
	if (tempOut)
		tempOut.textContent =
			source.temperature == null
				? "Not configured"
				: Number(source.temperature).toFixed(1);
	const topPOut = document.getElementById("val-top-p");
	if (topPOut)
		topPOut.textContent =
			source.top_p == null ? "Not configured" : Number(source.top_p).toFixed(2);
	const topKOut = document.getElementById("val-top-k");
	if (topKOut)
		topKOut.textContent =
			source.top_k == null ? "Not configured" : String(source.top_k);
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
			additional_instructions: getValueIfExists(
				"adv-additional-instructions",
				"",
			),
			enable_reasoning: getCheckedIfExists("adv-reasoning"),
			enable_vision: getCheckedIfExists("adv-vision"),
		};

		const response = await apiFetch("/api/v1/update_profile", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ updates }),
		});

		const result = await readJsonResponse(response);
		if (!response.ok || result.status !== "success") {
			throw new Error(getApiError(result, response.status));
		}
		Object.assign(appConfig.profile, updates);
		showSuccess("Advanced settings saved");
		loadAdvancedSettingsFromData(updates);
	} catch (error) {
		console.error("Error saving advanced settings:", error);
		showError("Error saving advanced settings");
	} finally {
		saveBtn.textContent = originalText;
		saveBtn.disabled = false;
	}
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
		const response = await apiFetch("/api/v1/clear_chat", {
			method: "POST",
			headers: { Accept: "application/json" },
		});
		const result = await readJsonResponse(response);
		if (!response.ok || result.status !== "success") {
			throw new Error(getApiError(result, response.status));
		}
		showSuccess("Chat history cleared successfully!");
		await loadProfileData();
	} catch (error) {
		console.error("Error clearing chat:", error);
		showError(`Could not clear chat history: ${error.message}`);
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

	const notification = document.createElement("div");
	notification.className = `config-notification ${type}`;
	notification.innerHTML = `
		<div class="notification-content">
			<span class="notification-icon">${type === "success" ? "✓" : type === "error" ? "✗" : "ℹ"}</span>
			<span class="notification-message">${escapeHtml(message)}</span>
			<button class="notification-close" type="button" data-action="dismiss-notification">×</button>
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

async function saveLocation() {
	const lat = Number.parseFloat(getValueIfExists("location-lat", ""));
	const lon = Number.parseFloat(getValueIfExists("location-lon", ""));
	if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
		showError("Enter both latitude and longitude before saving.");
		return;
	}

	try {
		const response = await apiFetch("/api/v1/update_location", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
			},
			body: JSON.stringify({ lat, lon }),
		});
		const data = await readJsonResponse(response);
		if (!response.ok || data.status !== "success") {
			throw new Error(getApiError(data, response.status));
		}
		appConfig.profile.location_lat = lat;
		appConfig.profile.location_lon = lon;
		showSuccess(data.message || "Location saved");
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

// ── Slider drag-guard ────────────────────────────────────────────────────
// Range inputs in this UI were firing during vertical page scroll
// (the thumb follows a tiny accidental horizontal jitter). This guard
// requires the pointer to commit to a *predominantly horizontal* drag
// before the slider starts emitting "input" events, and suppresses
// value changes from a near-vertical gesture.
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
		const response = await apiFetch("/api/v1/global-knowledge", {
			headers: { Accept: "application/json" },
		});
		const data = await readJsonResponse(response);
		if (!response.ok || data.status === "error") {
			throw new Error(getApiError(data, response.status));
		}
		renderGlobalKnowledge(data.entries || data || []);
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
		const response = await apiFetch(
			id
				? `/api/v1/global-knowledge/${encodeURIComponent(id)}`
				: "/api/v1/global-knowledge",
			{
				method: id ? "PUT" : "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify(payload),
			},
		);
		const data = await readJsonResponse(response);
		if (!response.ok || data.status !== "success") {
			throw new Error(getApiError(data, response.status));
		}
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
		const response = await apiFetch(
			`/api/v1/global-knowledge/${encodeURIComponent(id)}`,
			{ method: "DELETE", headers: { Accept: "application/json" } },
		);
		const data = await readJsonResponse(response);
		// DELETE returns 204 with an empty body; treat that as success.
		const emptyOk =
			response.status === 204 ||
			(data && typeof data === "object" && Object.keys(data).length === 0);
		if (!response.ok || (!emptyOk && data.status !== "success")) {
			throw new Error(getApiError(data, response.status));
		}
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

init();
