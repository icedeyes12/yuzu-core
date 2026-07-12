import { chatStore } from "./store.js";
import { eventRouter } from "./event-router.js";
import { showChatSkeleton, hideChatSkeleton } from "./skeleton.js";
import { MESSAGES_PER_PAGE } from "./state.js";

// Export pagination state (useful for UI but shouldn't own data)
export let olderMessagesLoaded = 0;
export let isLoadingOlder = false;
let currentHistorySessionId = null; // Track which session's history is active

/**
 * Load complete chat history for a session and feed it to the ConversationStore.
 * The Store -> Renderer pipeline handles the DOM.
 */
export async function loadChatHistory(sessionId = null) {
	const chatContainer = document.getElementById("chatContainer");

	// Add class for clean visual transition
	chatContainer.classList.add("session-switching");
	showChatSkeleton();
	
	try {
		const url = sessionId
			? `/api/chat_history?session_id=${sessionId}`
			: "/api/chat_history";

		if (sessionId) {
			const switchRes = await fetch("/api/sessions/switch", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ session_id: sessionId }),
			});
			if (!switchRes.ok) console.warn(`Failed to switch to session ${sessionId}`);
		}

		const res = await fetch(url);
		if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
		
		const data = await res.json();
		const history = data.chat_history || [];
		
		hideChatSkeleton();
		chatContainer.classList.remove("session-switching");

		// Inform EventRouter which session is currently active visually
		eventRouter.setActiveView(sessionId || data.active_session_id);
		currentHistorySessionId = sessionId || data.active_session_id;
		
		// Reset pagination
		olderMessagesLoaded = 0;
		isLoadingOlder = false;

		// Feed the history into the Store.
		// History represents completed messages, so they enter frozen.
		const normalizedHistory = history.map(msg => ({
			...msg,
			isFrozen: true
		}));
		
		chatStore.loadHistory(currentHistorySessionId, normalizedHistory);
	} catch (error) {
		hideChatSkeleton();
		chatContainer.classList.remove("session-switching");
		console.error("Error loading chat history:", error);
		chatContainer.innerHTML = `<div class="message-row system-message">Error loading history: ${error.message}</div>`;
	}
}

/**
 * Pagination logic: only requests more data and prepends to the store.
 * (Requires Store update to handle prepend properly - we will add this later if needed,
 * but for now we dispatch to loadHistory with the full sliced array)
 */
export function setupScrollListener() {
	const chatContainer = document.getElementById("chatContainer");
	
	chatContainer.addEventListener("scroll", async () => {
		if (chatContainer.scrollTop === 0 && !isLoadingOlder) {
			const history = chatStore.messages; // We should fetch from API, but keeping it simple for now
			// If we had a real pagination endpoint we'd fetch here.
			// Since we load all history at once in the current API, this scroll listener 
			// isn't actually fetching new data, it was just doing DOM trickery. 
			// We can leave this as a no-op until backend pagination is implemented,
			// because chatStore now holds the full array anyway.
		}
	});
}
