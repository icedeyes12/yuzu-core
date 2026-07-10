// FILE: static/js/modules/history.js
// DESCRIPTION: Chat history loading with pagination

import { captureDetailsState, restoreDetailsState } from "./dom-utils.js";
import {
	createMessageElement,
	findMessageById,
	isRenderableHistoryRole,
} from "./messages.js";
import { validateToolResult } from "./validator.js";

function formatToolCall(toolCall) {
	const toolName = toolCall.function?.name || "unknown";
	const callId = toolCall.id || "";
	return `\n<details class="tool-call-indicator"><summary>⚙️ Calling ${toolName}…</summary><pre data-call-id="${callId}">Completed ✓</pre></details>\n`;
}

export function formatToolResult(contentStr) {
	const parsed = validateToolResult(contentStr);
	const toolName = parsed.name;
	const ok = parsed.ok;
	const statusIcon = ok ? "✅" : "❌";
	
	let htmlContent = "";

	// Custom render for Terminal tool
	if (toolName === "terminal" && parsed.data) {
		const output = parsed.data.output || "(empty)";
		const exitCode = parsed.data.exit_code ?? 0;
		const duration = parsed.data.duration_ms ?? 0;

		htmlContent = `<div class="terminal-card" style="font-family: monospace; background: #000; color: #fff; padding: 10px; border-radius: 4px; overflow-x: auto;">
			<div style="color: #4ade80; margin-bottom: 8px;">$ ${parsed.data.command || "command"}</div>
			<pre style="margin: 0; white-space: pre-wrap;">${output}</pre>
			<div style="margin-top: 8px; color: ${exitCode === 0 ? '#4ade80' : '#f87171'}; font-size: 0.9em;">
				Exit: ${exitCode} | Time: ${duration}ms
			</div>
		</div>`;
	}

	// Custom render for Weather tool
	else if (toolName === "weather" && parsed.data && parsed.data.current) {
		const current = parsed.data.current;
		const temp = current.temperature_2m;
		const humidity = current.relative_humidity_2m;
		const code = current.weather_code;

		// WMO codes mapped to Lucide icons via CDN
		let iconName = "cloud";
		if (code <= 1) iconName = "sun";
		else if (code <= 3) iconName = "cloud-sun";
		else if (code <= 49) iconName = "cloud-fog";
		else if (code <= 69) iconName = "cloud-rain";
		else if (code <= 79) iconName = "cloud-snow";
		else if (code <= 99) iconName = "cloud-lightning";

		const iconUrl = `https://unpkg.com/lucide-static@0.344.0/icons/${iconName}.svg`;

		htmlContent = `<div class="weather-card" style="padding: 10px; background: rgba(255,255,255,0.05); border-radius: 8px; display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
			<div style="width: 48px; height: 48px; background-color: var(--accent-primary, currentColor); -webkit-mask: url('${iconUrl}') no-repeat center; mask: url('${iconUrl}') no-repeat center; -webkit-mask-size: contain; mask-size: contain;"></div>
			<div>
				<div style="font-size: 1.5rem; font-weight: bold;">${temp}°C</div>
				<div style="opacity: 0.8;">Humidity: ${humidity}%</div>
			</div>
		</div>`;
	}
	// Fallback raw object render
	else if (Object.keys(parsed.data).length > 0) {
		htmlContent = `<pre style="white-space: pre-wrap; font-size: 0.9em; margin: 0;">${JSON.stringify(parsed.data, null, 2)}</pre>`;
	} else if (parsed.error) {
		htmlContent = `<pre style="color: #f87171;">Error: ${parsed.error}</pre>`;
	} else {
		htmlContent = `<pre>${parsed.rawString}</pre>`;
	}

	if (parsed.data?.encoded_image_path) {
		const encodedPath = encodeURI(parsed.data.encoded_image_path);
		htmlContent += `\n\n<img src="${encodedPath}" alt="Tool Output Image">`;
	}

	return `\n<details class="tool-result" open><summary>${statusIcon} ${toolName}</summary><div class="tool-result-content">${htmlContent}</div></details>\n`;
}

import { scrollToBottom } from "./scroll.js";
import { hideChatSkeleton, showChatSkeleton } from "./skeleton.js";
import { MESSAGES_PER_PAGE } from "./state.js";

// Session switching guardrails
let _isLoadingHistory = false;
let _pendingSessionId = null;

/**
 * Load chat history for a session.
 * @param {number|null} sessionId - Session ID to load
 */
export async function loadChatHistory(sessionId = null) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;

	// Guard: Prevent concurrent history loads
	if (_isLoadingHistory) {
		console.log(
			`[History] Load already in progress for session ${_pendingSessionId}, ignoring request for ${sessionId}`,
		);
		return;
	}

	// Mark as loading
	_isLoadingHistory = true;
	_pendingSessionId = sessionId;

	// Fade out chat container for clean visual transition
	chatContainer.classList.add("session-switching");

	// Show skeleton loading
	showChatSkeleton();
	setTimeout(scrollToBottom, 50);

	try {
		// Build URL with optional session ID
		const url = sessionId
			? `/api/chat_history?session_id=${sessionId}`
			: "/api/chat_history";

		// Switch session on backend if needed
		if (sessionId) {
			const switchRes = await fetch("/api/sessions/switch", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ session_id: sessionId }),
			});

			if (!switchRes.ok) {
				console.warn(
					`Failed to switch to session ${sessionId}, loading default`,
				);
			}
		}

		const res = await fetch(url);
		if (!res.ok) {
			throw new Error(`HTTP ${res.status}: ${res.statusText}`);
		}
		const data = await res.json();
		const history = data.chat_history || [];

		// Hide skeleton before rendering real content
		hideChatSkeleton();

		// Fade container back in
		chatContainer.classList.remove("session-switching");

		// [TEXT OVERLAP FALLBACK] Check for active stream
		const activeStream = sessionId
			? window.backgroundStreams?.getStream(sessionId)
			: null;
		const hasActiveStream = activeStream?.isActive;

		if (history.length > 0) {
			chatContainer.innerHTML = "";
			console.log(`Processing ${history.length} messages from history`);

			// Load last 30 messages initially
			const messagesToShow = history.slice(-MESSAGES_PER_PAGE);

			const fragment = document.createDocumentFragment();

			let currentAiMessage = null;

			messagesToShow.forEach((msg, index) => {
				// [TEXT OVERLAP FALLBACK] Skip last AI message if we have an active stream
				// The stream will provide the complete/continuing content
				const isLastMessage = index === messagesToShow.length - 1;
				const isAIMessage = msg.role !== "user";

				if (hasActiveStream && isLastMessage && isAIMessage) {
					console.log(
						`[History] Skipping last AI message - active stream will handle it`,
					);
					return; // Skip this message
				}

				if (isRenderableHistoryRole(msg.role)) {
					if (msg.role === "tool") {
						if (currentAiMessage) {
							const contentDiv =
								currentAiMessage.querySelector(".message-content");
							if (contentDiv) {
								contentDiv.innerHTML += formatToolResult(msg.content);
							}
						}
						return; // Skip creating a new bubble for tool result
					}

					console.log("[History] Raw message before render:", {
						role: msg.role,
						preview: String(msg.content || "").slice(0, 200),
					});
					const contentToRender = msg.content;
					const msgElement = createMessageElement(
						msg.role === "user" ? "user" : "ai",
						contentToRender,
						msg.timestamp,
					);

					if (msg.role !== "user") {
						currentAiMessage = msgElement;
					}

					if (msg.tool_calls && msg.tool_calls.length > 0) {
						const callsHtml = msg.tool_calls.map(formatToolCall).join("");
						const contentDiv = msgElement.querySelector(".message-content");
						if (contentDiv) {
							contentDiv.innerHTML += callsHtml;
						}
					}
					fragment.appendChild(msgElement);
				}
			});

			chatContainer.appendChild(fragment);

			// [TEXT OVERLAP FALLBACK] If we have an active stream, create/fetch its message element
			if (hasActiveStream) {
				// [DOM REBIND FIX] Tell stream manager this session is now active
				window.backgroundStreams?.setActiveView(sessionId);

				console.log(
					`[History] Rebinding active stream for session ${sessionId}`,
				);
				let streamElement = findMessageById(activeStream.messageId);

				if (!streamElement) {
					streamElement = document.createElement("div");
					streamElement.className = "message ai";
					streamElement.setAttribute("data-streaming", "true");
					streamElement.setAttribute("data-message-id", activeStream.messageId);
					streamElement.innerHTML = `<div class="message-content"></div>`;
					chatContainer.appendChild(streamElement);
				}

				// Flush buffer with markdown rendering
				const contentDiv = streamElement.querySelector(".message-content");
				if (contentDiv && activeStream.buffer) {
					console.log(
						`[History] Flushing ${activeStream.buffer.length} chars from stream buffer`,
					);
					if (window.multimodal) {
						window.multimodal.renderStreamChunk(
							contentDiv,
							activeStream.buffer,
						);
					} else {
						// [ACCORDION PRESERVATION] Capture state before innerHTML update
						const detailsStates = captureDetailsState(contentDiv);
						contentDiv.innerHTML = activeStream.buffer;
						// [ACCORDION PRESERVATION] Restore state after innerHTML update
						restoreDetailsState(contentDiv, detailsStates);
					}
				}

				// Re-attach global state for legacy compatibility
				window.currentStreamMessage = streamElement;
				window.currentAbortController = activeStream.controller;

				// Restore UI state
				if (window.multimodal) {
					window.multimodal.setSendButtonState("sending");
				}
			}

			// Apply syntax highlighting to all code blocks after rendering
			setTimeout(() => {
				if (typeof hljs !== "undefined") {
					hljs.highlightAll();
				}
				if (typeof mermaid !== "undefined") {
					mermaid.init();
				}
				scrollToBottom();
				// Update layout after history render completes
				if (typeof window.updateDynamicLayout === "function") {
					window.updateDynamicLayout();
				}
			}, 100);

			// Add scroll event for loading older messages
			if (history.length > MESSAGES_PER_PAGE) {
				addScrollLoadListener(history);
			}

			console.log(`Displayed ${messagesToShow.length} recent messages`);
		} else {
			console.log("No chat history found");
			chatContainer.innerHTML = "";
			const { addMessage } = await import("./messages.js");
			addMessage(
				"ai",
				"Hello! I'm your AI companion. Let's start a new conversation!",
			);
			scrollToBottom();
			// Update layout even for empty state
			if (typeof window.updateDynamicLayout === "function") {
				window.updateDynamicLayout();
			}
		}
	} catch (err) {
		console.error("Failed to load chat history:", err);
		chatContainer.innerHTML = "";
		const { addMessage } = await import("./messages.js");
		addMessage(
			"ai",
			"Hello! I'm your AI companion. Let's start a new conversation!",
		);
		scrollToBottom();
		// Update layout on error too
		if (typeof window.updateDynamicLayout === "function") {
			window.updateDynamicLayout();
		}
	} finally {
		// Reset loading state
		_isLoadingHistory = false;
		_pendingSessionId = null;
		// Safety: always ensure fade class is removed even on error
		chatContainer.classList.remove("session-switching");
	}
}

/**
 * Add scroll listener for lazy-loading older messages.
 * @param {Array} fullHistory - Full history array
 */
export function addScrollLoadListener(fullHistory) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;

	let isLoadingOlder = false;
	let olderMessagesLoaded = 0;

	chatContainer.addEventListener("scroll", async () => {
		if (isLoadingOlder) return;

		// Check if scrolled to top
		if (chatContainer.scrollTop < 100) {
			const remainingMessages =
				fullHistory.length - MESSAGES_PER_PAGE - olderMessagesLoaded;

			if (remainingMessages > 0) {
				isLoadingOlder = true;

				const loadCount = Math.min(MESSAGES_PER_PAGE, remainingMessages);
				const startIndex =
					fullHistory.length -
					MESSAGES_PER_PAGE -
					olderMessagesLoaded -
					loadCount;
				const messagesToLoad = fullHistory.slice(
					startIndex,
					startIndex + loadCount,
				);

				console.log(`Loading ${loadCount} older messages...`);

				// Save scroll position
				const scrollHeightBefore = chatContainer.scrollHeight;

				const fragment = document.createDocumentFragment();

				let currentAiLazy = null;

				messagesToLoad.forEach((msg) => {
					if (isRenderableHistoryRole(msg.role)) {
						if (msg.role === "tool") {
							if (currentAiLazy) {
								const contentDiv =
									currentAiLazy.querySelector(".message-content");
								if (contentDiv) {
									contentDiv.innerHTML += formatToolResult(msg.content);
								}
							}
							return;
						}

						console.log("[History] Raw lazy-loaded message before render:", {
							role: msg.role,
							preview: String(msg.content || "").slice(0, 200),
						});
						const contentToRender = msg.content;
						const msgElement = createMessageElement(
							msg.role === "user" ? "user" : "ai",
							contentToRender,
							msg.timestamp,
						);

						if (msg.role !== "user") {
							currentAiLazy = msgElement;
						}

						if (msg.tool_calls && msg.tool_calls.length > 0) {
							const callsHtml = msg.tool_calls.map(formatToolCall).join("");
							const contentDiv = msgElement.querySelector(".message-content");
							if (contentDiv) {
								contentDiv.innerHTML += callsHtml;
							}
						}
						fragment.insertBefore(msgElement, fragment.firstChild);

						// because we iterate forward but insert before first child,
						// wait, messagesToLoad is chronological?
						// if it is, insertBefore(msgElement, firstChild) reverses the order!
						// Wait, the original code had: fragment.insertBefore(msgElement, fragment.firstChild);
						// Let's keep the logic matching the original insert order but fix the tool role tracking.
					}
				});

				chatContainer.insertBefore(fragment, chatContainer.firstChild);

				// Apply syntax highlighting to newly loaded messages
				setTimeout(() => {
					if (typeof hljs !== "undefined") {
						hljs.highlightAll();
					}
					if (typeof mermaid !== "undefined") {
						mermaid.init();
					}
				}, 100);

				// Restore scroll position
				const scrollHeightAfter = chatContainer.scrollHeight;
				chatContainer.scrollTop = scrollHeightAfter - scrollHeightBefore;

				olderMessagesLoaded += loadCount;
				isLoadingOlder = false;

				console.log(
					`Loaded ${loadCount} older messages. Total loaded: ${MESSAGES_PER_PAGE + olderMessagesLoaded}`,
				);
			}
		}
	});
}
