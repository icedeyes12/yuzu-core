// FILE: static/js/chat.js
// DESCRIPTION: Chat interface entry point - imports and initializes all modules
// ==================== MODULE IMPORTS ====================
import {
	chatStore,
	copyFullMessage,
	createScrollButton,
	eventRouter,
	findMessageById,
	generateMessageId,
	hideChatSkeleton,
	initializeInputBehavior,
	isRenderableHistoryRole,
	loadChatHistory,
	MESSAGES_PER_PAGE,
	MultimodalManager,
	router,
	scrollToBottom,
	showChatSkeleton,
} from "./modules/index.js";

// ==================== GLOBAL EXPORTS FOR MODULES ====================
// Make modules available globally for backward compatibility with inline handlers
window.router = router;
window.chatStore = chatStore;
window.eventRouter = eventRouter;

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

// ==================== FOCUS MANAGEMENT ====================
/**
 * Focus the chat input unless it is disabled.
 * Safe to call even when the input doesn't exist yet.
 */
function _focusChatInput() {
	const input = document.getElementById("messageInput");
	if (input && !input.disabled) {
		input.focus({ preventScroll: true });
	}
}

// ==================== SESSION SWITCH HANDLER ====================
/**
 * Handle session switch from URL or sidebar.
 * @param {number} sessionId - Target session ID
 * @param {boolean} updateURL - Whether to update browser URL (default: true)
 */
async function handleSessionSwitch(sessionId, updateURL = true) {
	if (!sessionId) return false;
	if (
		sessionId === router.currentSessionId &&
		chatStore.sessionId === sessionId &&
		chatStore.messages.length > 0 &&
		!chatStore.error
	) {
		return true;
	}
	if (updateURL) {
		router.updateUrl(sessionId);
	} else {
		router.currentSessionId = sessionId;
	}
	eventRouter.setActiveView(sessionId);
	const userInput = document.getElementById("messageInput");
	if (userInput) userInput.disabled = true;
	try {
		return await loadChatHistory(sessionId);
	} finally {
		if (userInput) userInput.disabled = false;
		_focusChatInput();
	}
}

// ==================== INITIALIZATION ====================
async function initializeChat() {
	if (window.__yuzuChatInitialized) return;
	window.__yuzuChatInitialized = true;

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
			router.currentSessionId = sessionId;
			eventRouter.setActiveView(sessionId);
			await loadChatHistory(sessionId);
			if (typeof window.syncActiveSidebarItem === "function")
				window.syncActiveSidebarItem(sessionId);
		} else {
			chatStore.setError("No active conversation is available.");
		}

		// Initialize multimodal
		window.multimodal = new MultimodalManager();
		window.multimodal.init();

		// Auto-focus input on initial load
		_focusChatInput();
	} catch (error) {
		chatStore.setError(error.message || "Chat initialization failed.");
	}
}

// ==================== GLOBAL EXPORTS ====================
// Export functions that are called from HTML or other scripts
window.scrollToBottom = scrollToBottom;
window.copyFullMessage = copyFullMessage;
window.loadChatHistory = loadChatHistory;
window.handleSessionSwitch = handleSessionSwitch;
window.isRenderableHistoryRole = isRenderableHistoryRole;
window.MESSAGES_PER_PAGE = MESSAGES_PER_PAGE;
window.generateMessageId = generateMessageId;
window.findMessageById = findMessageById;
window.showChatSkeleton = showChatSkeleton;
window.hideChatSkeleton = hideChatSkeleton;

// Start when the module is evaluated, regardless of whether window.onload
// has already fired while external assets were loading.
if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", () => void initializeChat(), {
		once: true,
	});
} else {
	void initializeChat();
}
