// FILE: static/js/config.js
// DESCRIPTION: Configuration page functionality

import { render as renderBadge } from "./badge-registry.js";
import {
	DEFAULT_YUZU_PORTAL_BASE_URL,
	encodeByokConfig,
	getByokConfig,
	getByokProvider,
	getUserStorageKey,
	writeByokConfig,
} from "./client-storage.js";
import { listProviders } from "./provider-registry.js";
import { toggleSidebar } from "./sidebar.js";
import { renderLogo } from "./visual-registry.js";

// Global config state (populated from /api/config)
let appConfig = null;

const PROVIDER_MODELS_CACHE_KEY = getUserStorageKey("provider_models");

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

function getProfileAdvancedSource(data) {
	return data?.advanced || data?.profile || data || {};
}

document.addEventListener("DOMContentLoaded", async () => {
	console.log("Config page loaded - initializing...");
	const loaded = await loadAppConfig();
	if (!loaded) return;
	await Promise.all([loadGlobalKnowledge(), loadProviderSettings()]);
	setupEventListeners();
	initializeConfigAnimations();
});

// Load application configuration from backend (SSOT)
async function loadAppConfig() {
	try {
		const response = await fetch("/api/config", {
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
	setValueIfExists("persona-preset", data.persona_preset || "helpful");
	setValueIfExists("persona-prompt", data.persona_prompt || "");
	setValueIfExists("location-lat", data.location_lat ?? "");
	setValueIfExists("location-lon", data.location_lon ?? "");
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
			const provUrl =
				provider === "yuzu_portal"
					? providerConfig.base_url || DEFAULT_YUZU_PORTAL_BASE_URL
					: providerConfig.base_url || "";

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
							<input type="password" id="key-${provider}" class="provider-flex-input" placeholder="sk-..." autocomplete="off" value="${provKey}">
							<button class="btn btn-secondary btn-sm save-byok-btn" type="button" data-provider="${provider}">Save Key</button>
						</div>
					</div>
`;

			if (isCustom || provider === "yuzu_portal") {
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
			grid.appendChild(card);

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

function saveBYOKForProvider(provider) {
	const keyInput = document.getElementById(`key-${provider}`);
	if (!keyInput) return;

	const byok = getByokConfig();
	const providerConfig = getByokProvider(provider);
	providerConfig.api_key = keyInput.value.trim();

	if (provider === "yuzu_portal") {
		const baseInput = document.getElementById("url-yuzu_portal");
		providerConfig.base_url =
			baseInput?.value.trim() || DEFAULT_YUZU_PORTAL_BASE_URL;
	} else if (provider.startsWith("custom")) {
		const baseInput = document.getElementById(`url-${provider}`);
		providerConfig.base_url = baseInput?.value.trim() || "";
	}

	byok.providers[provider] = providerConfig;
	if (!writeByokConfig(byok)) {
		showError("User scope is unavailable; provider key was not saved.");
		return;
	}
	showSuccess(`${provider} key saved in browser.`);
	updateImageModelWarning(getValueIfExists("image-model"));
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
	if (PROVIDER_MODELS_CACHE_KEY) {
		localStorage.setItem(PROVIDER_MODELS_CACHE_KEY, JSON.stringify(catalog));
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

		const response = await fetch(`/api/proxy/models/${provider}/refresh`, {
			method: "POST",
			headers: { ...headers, Accept: "application/json" },
		});
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

		const response = await fetch("/api/providers/test_connection", {
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
	const selected = IMAGE_MODEL_OPTIONS.find((option) => option.value === imageModel);
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
		const response = await fetch("/api/update_profile", {
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
		const response = await fetch("/api/providers/set_preferred", {
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
			headers: { "Content-Type": "application/json" },
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
		const result = await readJsonResponse(response);
		if (!response.ok || result.status !== "success") {
			throw new Error(getApiError(result, response.status));
		}
		Object.assign(appConfig.profile, {
			user_name: displayName,
			partner_name: partnerName,
			affection: parseInt(affection, 10),
			persona_preset: personaPreset,
			persona_prompt: personaPrompt,
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
		source.additional_instructions ?? "",
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
		const response = await fetch("/api/clear_chat", {
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
		const response = await fetch("/api/update_location", {
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
		const response = await fetch(
			`/api/global-knowledge/${encodeURIComponent(id)}`,
			{ method: "DELETE", headers: { Accept: "application/json" } },
		);
		const data = await readJsonResponse(response);
		if (!response.ok || data.status !== "success") {
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
