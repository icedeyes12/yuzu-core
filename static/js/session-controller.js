import { eventRouter } from "./modules/event-router.js";
import { loadChatHistory } from "./modules/history.js";
import { router } from "./modules/router.js";
import { chatStore } from "./modules/store.js";

export async function handleSessionSwitch(sessionId, updateURL = true) {
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
		focusChatInput();
	}
}

export function focusChatInput() {
	const input = document.getElementById("messageInput");
	if (input && !input.disabled) input.focus({ preventScroll: true });
}

export async function initializeChatSession(sessionId) {
	if (!sessionId) return false;
	router.currentSessionId = sessionId;
	eventRouter.setActiveView(sessionId);
	await loadChatHistory(sessionId);
	return true;
}

export function getSessionRuntime() {
	return { router, eventRouter, chatStore };
}
