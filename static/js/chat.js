// FILE: static/js/chat.js
// DESCRIPTION: Chat interface entry point - imports and initializes all modules
// ==================== MODULE IMPORTS ====================

import {
	chatStore,
	createScrollButton,
	initializeInputBehavior,
	MultimodalManager,
} from "./modules/index.js";
import { router } from "./modules/router.js";
import {
	focusChatInput,
	handleSessionSwitch,
	initializeChatSession,
} from "./session-controller.js";

// ==================== SESSION NAME LOADING ====================
async function loadCurrentSessionName() {
	try {
		const response = await fetch("/api/profile", {
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

// ==================== INITIALIZATION ====================
async function initializeChat() {
	if (document.body.dataset.yuzuChatInitialized === "true") return;
	document.body.dataset.yuzuChatInitialized = "true";

	try {
		// Initialize scroll button
		createScrollButton();

		// Initialize input behavior
		initializeInputBehavior();

		// Initialize URL router
		const urlSessionId = router.initFromURL(handleSessionSwitch);

		// Load session name
		await loadCurrentSessionName();

		// Stream state is now fully managed by ConversationStore + EventRouter

		let sessionId = urlSessionId;
		if (!sessionId) {
			const profileResponse = await fetch("/api/profile", {
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

		// Initialize multimodal
		const multimodal = new MultimodalManager();
		multimodal.init();

		// Auto-focus input on initial load
		focusChatInput();
	} catch (error) {
		chatStore.setError(error.message || "Chat initialization failed.");
	}
}

// Start when the module is evaluated, regardless of whether window.onload
// has already fired while external assets were loading.
if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", () => void initializeChat(), {
		once: true,
	});
} else {
	void initializeChat();
}
