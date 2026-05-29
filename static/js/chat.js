// FILE: static/js/chat.js
// DESCRIPTION: Chat interface entry point - imports and initializes all modules
console.log("Starting clean chat rebuild...");

// ==================== MODULE IMPORTS ====================
import {
	addMessage,
	backgroundStreams,
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
window.backgroundStreams = backgroundStreams;

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
	} catch (error) {
		console.error("Failed to load session name:", error);
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

	// [CRITICAL] Set active view BEFORE any DOM operations
	backgroundStreams.setActiveView(sessionId);

	// Update URL if needed
	if (updateURL) {
		router.updateURL(sessionId);
	}

	// [DOM REBIND FIX] Always load history, let loadChatHistory handle stream rebinding
	// This ensures previous messages are shown even when there's an active stream
	await loadChatHistory(sessionId);
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

	// [CRITICAL] Set active view to URL session (or null)
	backgroundStreams.setActiveView(urlSessionId);

	// Check if returning to a session with active stream
	if (urlSessionId && backgroundStreams.hasActiveStream(urlSessionId)) {
		console.log(
			`[Init] Session ${urlSessionId} has active stream, resuming...`,
		);

		const stream = backgroundStreams.getStream(urlSessionId);
		const chatContainer = document.getElementById("chatContainer");

		if (stream && chatContainer) {
			// Find or create message element
			let messageElement = findMessageById(stream.messageId);

			if (!messageElement) {
				// Create message element
				messageElement = document.createElement("div");
				messageElement.className = "message ai";
				messageElement.setAttribute("data-streaming", "true");
				messageElement.setAttribute("data-message-id", stream.messageId);
				messageElement.innerHTML = `<div class="message-content"></div>`;
				chatContainer.appendChild(messageElement);
			}

			// Flush buffer
			const contentDiv = messageElement.querySelector(".message-content");
			if (contentDiv && stream.buffer) {
				console.log(
					`[Init] Flushing ${stream.buffer.length} chars from buffer`,
				);
				// Use simple text rendering for init, full render will happen on next chunk
				contentDiv.innerHTML = stream.buffer;
				scrollToBottom();
			}

			// Re-attach global state
			window.currentStreamMessage = messageElement;
			window.currentAbortController = stream.controller;
			window.isProcessingMessage = true;

			// Restore UI state
			if (window.multimodal) {
				window.multimodal.setSendButtonState("sending");
			}

			// Don't load history - stream is active
			// Initialize multimodal and return
			window.multimodal = new MultimodalManager();
			window.multimodal.init();
			return;
		}
	}

	// Normal initialization - load history
	if (urlSessionId) {
		loadChatHistory(urlSessionId);
	} else {
		loadChatHistory();
	}

	// Initialize multimodal
	window.multimodal = new MultimodalManager();
	window.multimodal.init();

	console.log("Clean chat system ready!");
}

// ==================== GLOBAL EXPORTS ====================
// Export functions that are called from HTML or other scripts
window.addMessage = addMessage;
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
