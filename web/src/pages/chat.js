// Ported from static/js/chat.js: chat entry point that initializes the
// ConversationStore -> DOMRenderer pipeline, the URL router, the multimodal
// manager, and session handling. API calls route through apiFetch (session
// cookie, BYOK header injection, 401 auth gate).

import { bootApp } from "../main.js";
import { apiFetch } from "../modules/apiFetch.js";
import {
	chatStore,
	createScrollButton,
	initializeInputBehavior,
	initializeMessageActions,
	MultimodalManager,
} from "../modules/index.js";
import "../modules/vendor.js";
import { router } from "../modules/router.js";
import {
	focusChatInput,
	initializeChatSession,
} from "../modules/session-controller.js";

/**
 * Loads the current session and partner names into the chat interface.
 */
async function loadCurrentSessionName() {
	try {
		const response = await apiFetch("/api/v1/profile", {
			headers: { Accept: "application/json" },
		});
		if (!response.ok)
			throw new Error(`HTTP ${response.status}: ${response.statusText}`);
		const data = await response.json();

		const sessionNameElement = document.getElementById("sessionName");
		if (sessionNameElement && data.active_session) {
			sessionNameElement.textContent =
				data.active_session.name || "Current Chat";
		}

		// Reflect partner/user name in header if present
		const partnerEl = document.getElementById("partnerName");
		if (partnerEl && data.partner_name) {
			partnerEl.textContent = data.partner_name;
		}
	} catch (error) {
		chatStore.setError(error.message || "Failed to load profile.");
	}
}

/**
 * Initialize the chat interface and active conversation.
 */
async function initializeChat() {
	if (document.body.dataset.yuzuChatInitialized === "true") return;
	document.body.dataset.yuzuChatInitialized = "true";

	try {
		// Initialize scroll button
		createScrollButton();

		// Initialize input behavior
		initializeInputBehavior();
		initializeMessageActions();

		// Initialize URL router
		const urlSessionId = router.initFromURL();

		// Load session name
		await loadCurrentSessionName();

		// Stream state is now fully managed by ConversationStore + EventRouter

		let sessionId = urlSessionId;
		if (!sessionId) {
			const profileResponse = await apiFetch("/api/v1/profile", {
				headers: { Accept: "application/json" },
			});
			if (!profileResponse.ok)
				throw new Error(
					`HTTP ${profileResponse.status}: ${profileResponse.statusText}`,
				);
			const profileData = await profileResponse.json();
			sessionId = profileData.active_session?.id;
		}
		if (sessionId) {
			await initializeChatSession(sessionId);
		} else {
			chatStore.setError("No active conversation is available.");
		}

		// Initialize multimodal from the same canonical model metadata as config.
		const configResponse = await apiFetch("/api/v1/config", {
			headers: { Accept: "application/json" },
		});
		const config = configResponse.ok ? await configResponse.json() : {};
		const provider =
			config.current_provider || config.ai_providers?.current_provider;
		const model = config.current_model || config.ai_providers?.current_model;
		const modelInfo = (config.model_infos?.[provider] || []).find(
			(info) => info.id === model,
		);
		const multimodal = new MultimodalManager(modelInfo);
		multimodal.init();

		// Auto-focus input on initial load
		focusChatInput();
	} catch (error) {
		chatStore.setError(error.message || "Chat initialization failed.");
	}
}

/**
 * Boots the chat page and initializes it for authenticated users.
 */
async function init() {
	const me = await bootApp({ page: "chat" });
	if (!me) return; // User unauthenticated, bootApp already triggers redirect to /login
	await initializeChat();
}

init();
