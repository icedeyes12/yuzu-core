import { eventRouter } from "./event-router.js";
import { hideChatSkeleton, showChatSkeleton } from "./skeleton.js";
import { chatStore } from "./store.js";

export let olderMessagesLoaded = 0;
export let isLoadingOlder = false;
let currentHistorySessionId = null;
let historyRequest = null;
let historyRequestSequence = 0;

export async function loadChatHistory(sessionId = null) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return false;
	const requestedSessionId = sessionId || null;
	const requestId = ++historyRequestSequence;
	historyRequest?.abort();
	historyRequest = new AbortController();
	chatContainer.classList.add("session-switching");
	showChatSkeleton();

	try {
		let data;
		if (requestedSessionId) {
			const switchRes = await fetch("/api/sessions/switch", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify({ session_id: requestedSessionId }),
				signal: historyRequest.signal,
			});
			if (!switchRes.ok)
				throw new Error(`HTTP ${switchRes.status}: session switch failed`);
			data = await switchRes.json();
		} else {
			const res = await fetch("/api/chat_history?limit=50", {
				headers: { Accept: "application/json" },
				signal: historyRequest.signal,
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
			data = await res.json();
		}
		const responseSessionId =
			requestedSessionId ||
			data.active_session_id ||
			(requestedSessionId ? null : data.active_session?.id) ||
			null;
		if (
			requestId !== historyRequestSequence ||
			eventRouter.activeViewSessionId !== responseSessionId
		)
			return false;

		const history = Array.isArray(data.chat_history) ? data.chat_history : [];
		currentHistorySessionId = responseSessionId;
		if (!currentHistorySessionId)
			throw new Error("History response did not identify a session.");
		eventRouter.setActiveView(currentHistorySessionId);
		olderMessagesLoaded = 0;
		isLoadingOlder = false;
		chatStore.loadHistory(currentHistorySessionId, history);
		return true;
	} catch (error) {
		if (error.name !== "AbortError" && requestId === historyRequestSequence) {
			chatStore.setError(
				error.message || "Failed to load conversation history.",
			);
			return false;
		}
		return false;
	} finally {
		if (requestId === historyRequestSequence) {
			hideChatSkeleton();
			chatContainer.classList.remove("session-switching");
			historyRequest = null;
		}
	}
}

export function setupScrollListener() {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;
	chatContainer.addEventListener("scroll", () => {});
}
