// FILE: static/js/chat.js
// DESCRIPTION: Chat interface entry point - imports and initializes all modules
console.log("Starting clean chat rebuild...");

// ==================== MODULE IMPORTS ====================
import {
	copyFullMessage,
	createScrollButton,
	findMessageById,
	generateMessageId,
	hideChatSkeleton,
	initializeInputBehavior,
	isRenderableHistoryRole,
	loadChatHistory,
	MESSAGES_PER_PAGE,
	MultimodalManager,
	renderMessageContent,
	router,
	scrollToBottom,
	showChatSkeleton,
} from "./modules/index.js";

// ==================== GLOBAL EXPORTS FOR MODULES ====================
// Make modules available globally for backward compatibility with inline handlers
window.router = router;

// ==================== SESSION NAME LOADING ====================
async function loadCurrentSessionName() {
	try {
		const response = await fetch("/api/profile");
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
		console.error("Failed to load session name:", error);
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
	console.log(`[Chat] Switching to session ${sessionId}`);

	// 1. Update currentSessionId
	router.currentSessionId = sessionId;

	// [CRITICAL] Set active view BEFORE any DOM operations
	backgroundStreams.setActiveView(sessionId);

	// Update URL if needed
	if (updateURL) {
		router.updateURL(sessionId);
	}

	// Sync sidebar active highlight immediately (no reload needed)
	if (typeof window.syncActiveSidebarItem === "function") {
		window.syncActiveSidebarItem(sessionId);
	}

	// 2. Hide previous session completely (we don't wait for the network request)
	const chatContainer = document.getElementById("chatContainer");
	if (chatContainer) {
		chatContainer.innerHTML = ""; // Handled by Store clearing now, but keeping for intermediate visual clear before fetch
	}

	// 4. Disable the chat input during this transition
	const userInput = document.getElementById("userInput");
	if (userInput) userInput.disabled = true;

	// 3. Fire loadChatHistory(newSessionId) to render the new messages
	// [DOM REBIND FIX] Always load history, let loadChatHistory handle stream rebinding
	// This ensures previous messages are shown even when there's an active stream
	await loadChatHistory(sessionId);

	if (userInput) userInput.disabled = false;

	// Auto-focus input after session content loads
	_focusChatInput();
}

// ==================== INITIALIZATION ====================
async function initializeChat() {
	console.log("Initializing clean chat system...");

	// Initialize scroll button
	createScrollButton();

	// Initialize input behavior
	initializeInputBehavior();

	// Initialize URL router
	const urlSessionId = router.initFromURL();

	// Load session name
	loadCurrentSessionName();

	// Stream state is now fully managed by ConversationStore + EventRouter

	// Normal initialization - load history
	if (urlSessionId) {
		await loadChatHistory(urlSessionId);
	} else {
		const input = document.getElementById("messageInput");
		const btn = document.getElementById("sendButton");
		if (input) {
			input.disabled = true;
			input.placeholder = "No active session selected...";
		}
		if (btn) btn.disabled = true;
		console.error("No session ID in URL path. Chat disabled.");
		await loadChatHistory();
	}

	// Initialize multimodal
	window.multimodal = new MultimodalManager();
	window.multimodal.init();

	// Auto-focus input on initial load
	_focusChatInput();

	console.log("Clean chat system ready!");
}

// ==================== GLOBAL EXPORTS ====================
// Export functions that are called from HTML or other scripts
window.scrollToBottom = scrollToBottom;
window.copyFullMessage = copyFullMessage;
window.loadChatHistory = loadChatHistory;
window.handleSessionSwitch = handleSessionSwitch;
window.renderMessageContent = renderMessageContent;
window.isRenderableHistoryRole = isRenderableHistoryRole;
window.MESSAGES_PER_PAGE = MESSAGES_PER_PAGE;
window.generateMessageId = generateMessageId;
window.findMessageById = findMessageById;
window.showChatSkeleton = showChatSkeleton;
window.hideChatSkeleton = hideChatSkeleton;

// Start when page loads
window.onload = () => {
	initializeChat();
};
