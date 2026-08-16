import { apiFetch } from "./apiFetch.js";
import { eventRouter } from "./event-router.js";
import { hideChatSkeleton, showChatSkeleton } from "./skeleton.js";
import { chatStore } from "./store.js";

export let olderMessagesLoaded = 0;
export let isLoadingOlder = false;
let currentHistorySessionId = null;
let historyRequest = null;
let historyRequestSequence = 0;
let scrollListenerAttached = false;

/**
 * Loads older messages for the active chat session when additional history is available.
 * @throws {Error} If the history request returns an unsuccessful response.
 */
async function _loadOlderMessages() {
	if (isLoadingOlder || !chatStore.hasMoreOlder || !currentHistorySessionId)
		return;

	// Oldest message visible — use its timestamp as the cursor
	const oldest = chatStore.messages[0];
	if (!oldest) return;
	const beforeTs = oldest.timestamp;
	if (!beforeTs) return;

	isLoadingOlder = true;
	const chatContainer = document.getElementById("chatContainer");

	try {
		const res = await apiFetch(
			`/api/v1/chat_history/before?session_id=${encodeURIComponent(currentHistorySessionId)}&before_ts=${encodeURIComponent(beforeTs)}&limit=50`,
			{ headers: { Accept: "application/json" } },
		);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const data = await res.json();
		const older = Array.isArray(data.chat_history) ? data.chat_history : [];

		// Preserve scroll position before prepending
		const oldScrollHeight = chatContainer ? chatContainer.scrollHeight : 0;
		chatStore.prependHistory(older, data.has_more ?? false);
		// Scroll correction happens in DOMRenderer on "prepend" event using saved oldScrollHeight.
		// We stash it on the container so the renderer can pick it up.
		if (chatContainer) chatContainer._prependOldScrollHeight = oldScrollHeight;

		olderMessagesLoaded += older.length;
	} finally {
		isLoadingOlder = false;
	}
}

/**
 * Attach a throttled scroll listener that loads older messages near the top of the chat container.
 * @param {HTMLElement} chatContainer - The container whose scroll position triggers pagination.
 */
function _setupScrollListener(chatContainer) {
	if (scrollListenerAttached) return;
	scrollListenerAttached = true;

	let ticking = false;
	chatContainer.addEventListener("scroll", () => {
		if (ticking) return;
		ticking = true;
		requestAnimationFrame(() => {
			ticking = false;
			if (chatContainer.scrollTop < 100) {
				void _loadOlderMessages();
			}
		});
	});
}

/**
 * Loads chat history for the requested session or the default active session.
 * @param {string|null} [sessionId=null] - The session identifier to load.
 * @return {Promise<boolean>} `true` if the history loads successfully, `false` otherwise.
 */
export async function loadChatHistory(sessionId = null) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return false;
	const requestedSessionId = sessionId || null;
	const requestId = ++historyRequestSequence;
	historyRequest?.abort();
	historyRequest = new AbortController();
	chatContainer.classList.add("session-switching");
	showChatSkeleton();
	scrollListenerAttached = false;

	try {
		let data;
		if (requestedSessionId) {
			const switchRes = await apiFetch("/api/v1/sessions/switch", {
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
			const res = await apiFetch("/api/v1/chat_history?limit=50", {
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

		// Update active session name in header from the sidebar entry, or fallback.
		const sessionNameEl = document.getElementById("sessionName");
		if (sessionNameEl) {
			const sidebarItem = document.querySelector(
				`.sidebar-session-item[data-session-id="${currentHistorySessionId}"] .sidebar-session-name`,
			);
			if (sidebarItem?.textContent.trim()) {
				sessionNameEl.textContent = sidebarItem.textContent.trim();
			} else {
				sessionNameEl.textContent = "Current Chat";
			}
		}

		chatStore.loadHistory(
			currentHistorySessionId,
			history,
			data.has_more || false,
		);
		_setupScrollListener(chatContainer);
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
