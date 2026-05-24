// FILE: static/js/chat.js
// DESCRIPTION: Chat interface interactions
console.log("Starting clean chat rebuild...");

// ==================== GLOBAL STATE ====================
let isProcessingMessage = false;
const _currentPage = 0;
const MESSAGES_PER_PAGE = 30;

// ==================== STREAMING STATE ====================
let currentStreamMessage = null;
let currentAbortController = null;

// ==================== URL ROUTING MANAGER ====================
/**
 * Handles URL-based session routing for shareable URLs.
 * Enables /chat?session=123 style navigation without page reloads.
 */
class RouterManager {
	constructor() {
		this.currentSessionId = null;
		this.isInitialized = false;
	}

	/**
	 * Initialize router from current URL on page load.
	 * @returns {number|null} Session ID from URL or null
	 */
	initFromURL() {
		const params = new URLSearchParams(window.location.search);
		const sessionId = params.get("session");

		if (sessionId) {
			this.currentSessionId = parseInt(sessionId, 10);
			console.log(
				`[Router] Initialized with session ${this.currentSessionId} from URL`,
			);
		}

		this.isInitialized = true;
		this.setupPopStateHandler();
		return this.currentSessionId;
	}

	/**
	 * Update URL to reflect current session without page reload.
	 * @param {number} sessionId - Session ID to set in URL
	 */
	updateURL(sessionId) {
		if (!sessionId || sessionId === this.currentSessionId) return;

		this.currentSessionId = sessionId;
		const url = new URL(window.location.href);
		url.searchParams.set("session", sessionId.toString());

		window.history.pushState({ sessionId }, "", url);
		console.log(`[Router] URL updated to session ${sessionId}`);
	}

	/**
	 * Clear session parameter from URL.
	 */
	clearURL() {
		const url = new URL(window.location.href);
		url.searchParams.delete("session");
		window.history.pushState({}, "", url);
		this.currentSessionId = null;
	}

	/**
	 * Setup browser back/forward navigation handler.
	 */
	setupPopStateHandler() {
		window.addEventListener("popstate", (_event) => {
			const params = new URLSearchParams(window.location.search);
			const sessionId = params.get("session");

			if (sessionId && parseInt(sessionId, 10) !== this.currentSessionId) {
				console.log(`[Router] PopState: switching to session ${sessionId}`);
				this.currentSessionId = parseInt(sessionId, 10);
				// Trigger session switch without pushState
				if (typeof window.handleSessionSwitch === "function") {
					window.handleSessionSwitch(this.currentSessionId, false);
				}
			}
		});
	}
}

// ==================== BACKGROUND STREAM MANAGER ====================
/**
 * Manages SSE stream buffering for session switches mid-generation.
 * Allows streams to continue in background and resume on return.
 */
class BackgroundStreamManager {
	constructor() {
		// Map of sessionId -> { buffer, controller, messageElement, accumulatedText }
		this.activeStreams = new Map();
	}

	/**
	 * Start tracking a stream for a session.
	 * @param {number} sessionId - Session ID
	 * @param {AbortController} controller - AbortController for the stream
	 * @param {HTMLElement} messageElement - The message DOM element
	 */
	startStream(sessionId, controller, messageElement) {
		this.activeStreams.set(sessionId, {
			buffer: [],
			controller,
			messageElement,
			accumulatedText: "",
			isPaused: false,
		});
		console.log(`[BackgroundStream] Started tracking session ${sessionId}`);
	}

	/**
	 * Check if a session has an active stream.
	 * @param {number} sessionId - Session ID
	 * @returns {boolean}
	 */
	hasActiveStream(sessionId) {
		return this.activeStreams.has(sessionId);
	}

	/**
	 * Pause a stream (keep alive, buffer chunks).
	 * Called when switching away from a session with active generation.
	 * @param {number} sessionId - Session ID
	 */
	pauseStream(sessionId) {
		const stream = this.activeStreams.get(sessionId);
		if (stream) {
			stream.isPaused = true;
			// Hide the message element from DOM
			if (stream.messageElement?.parentNode) {
				stream.messageElement.dataset.paused = "true";
			}
			console.log(`[BackgroundStream] Paused stream for session ${sessionId}`);
		}
	}

	/**
	 * Resume a paused stream.
	 * Called when returning to a session with buffered content.
	 * @param {number} sessionId - Session ID
	 * @param {HTMLElement} chatContainer - The chat container to append to
	 * @returns {object|null} Stream data or null if not found
	 */
	resumeStream(sessionId, chatContainer) {
		const stream = this.activeStreams.get(sessionId);
		if (!stream) return null;

		stream.isPaused = false;

		// Re-attach message element to DOM
		if (stream.messageElement) {
			stream.messageElement.dataset.paused = "false";
			if (!stream.messageElement.parentNode && chatContainer) {
				chatContainer.appendChild(stream.messageElement);
			}
		}

		console.log(`[BackgroundStream] Resumed stream for session ${sessionId}`);
		return stream;
	}

	/**
	 * Cancel a stream.
	 * @param {number} sessionId - Session ID
	 */
	cancelStream(sessionId) {
		const stream = this.activeStreams.get(sessionId);
		if (stream) {
			if (stream.controller && !stream.controller.signal.aborted) {
				stream.controller.abort();
			}
			this.activeStreams.delete(sessionId);
			console.log(
				`[BackgroundStream] Cancelled stream for session ${sessionId}`,
			);
		}
	}

	/**
	 * Complete and clean up a stream.
	 * @param {number} sessionId - Session ID
	 */
	completeStream(sessionId) {
		this.activeStreams.delete(sessionId);
		console.log(`[BackgroundStream] Completed stream for session ${sessionId}`);
	}

	/**
	 * Update accumulated text for a stream.
	 * @param {number} sessionId - Session ID
	 * @param {string} text - Accumulated text
	 */
	updateText(sessionId, text) {
		const stream = this.activeStreams.get(sessionId);
		if (stream) {
			stream.accumulatedText = text;
		}
	}
}

// Global instances
const router = new RouterManager();
const backgroundStreams = new BackgroundStreamManager();

// ==================== SKELETON LOADING ====================
/**
 * Show skeleton loading state in chat container.
 */
function showChatSkeleton() {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;

	chatContainer.innerHTML = `
		<div class="skeleton-message ai">
			<div class="skeleton skeleton-message-line"></div>
			<div class="skeleton skeleton-message-line"></div>
			<div class="skeleton skeleton-message-line"></div>
		</div>
		<div class="skeleton-message user">
			<div class="skeleton skeleton-message-line"></div>
			<div class="skeleton skeleton-message-line"></div>
		</div>
		<div class="skeleton-message ai">
			<div class="skeleton skeleton-message-line"></div>
			<div class="skeleton skeleton-message-line"></div>
			<div class="skeleton skeleton-message-line"></div>
		</div>
	`;
}

/**
 * Hide skeleton and prepare for real content.
 */
function hideChatSkeleton() {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;

	const skeletons = chatContainer.querySelectorAll(".skeleton-message");
	for (const s of skeletons) {
		s.remove();
	}
}

// ==================== MULTIMODAL MANAGER ====================
class MultimodalManager {
	constructor() {
		this.currentMode = "chat";
		this.visualMode = false;
		this.selectedImages = [];
		this.isDropdownOpen = false;
		this.isSending = false;
	}

	init() {
		console.log("Initializing Multimodal...");
		this.createToggle();
		this.setupEventListeners();
		this.patchSendButton();
		this.updateNotificationCount();
	}

	createToggle() {
		const inputArea = document.querySelector(".input-area");
		if (!inputArea || inputArea.querySelector(".multimodal-toggle-container"))
			return;

		const toggleHTML = `
            <div class="multimodal-toggle-container">
                <button class="multimodal-toggle-btn" type="button" title="Multimodal Mode">
                    <span class="toggle-icon">${this.getSVGIcon("chat")}</span>
                    <div class="mode-indicator">C</div>
                    <div class="image-count-badge hidden">0</div>
                </button>
            </div>
        `;

		inputArea.insertAdjacentHTML("afterbegin", toggleHTML);
		this.toggleBtn = inputArea.querySelector(".multimodal-toggle-btn");
		this.modeIndicator = inputArea.querySelector(".mode-indicator");
		this.imageCountBadge = inputArea.querySelector(".image-count-badge");
	}

	getSVGIcon(mode) {
		const icons = {
			chat: `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm8 5H6v-2h8v2zm4-6H6V6h12v2z"/>
                   </svg>`,
			image: `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM5 19l3.5-4.5 2.5 3.01L14.5 11l4.5 6H5z"/>
                   </svg>`,
			generate: `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM5 19l3.5-4.5 2.5 3.01L14.5 11l4.5 6H5z"/>
                      <path d="M14.5 11l1.5-2 1.5 2 2-1-2-1.5 2-1.5-2-1-1.5 2-1.5-2-1 1.5L13 8l-1.5 2z" opacity="0.7"/>
                     </svg>`,
			download: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
                     </svg>`,
			regenerate: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
                       </svg>`,
			close: `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                   <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                  </svg>`,
			upload: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/>
                   </svg>`,
			copy: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                 </svg>`,
		};
		return icons[mode] || icons.chat;
	}

	setupEventListeners() {
		if (!this.toggleBtn) return;

		this.toggleBtn.addEventListener("click", (e) => {
			e.preventDefault();
			this.toggleDropdown();
		});

		document.addEventListener("click", (e) => {
			if (!e.target.closest(".multimodal-toggle-container")) {
				this.closeDropdown();
			}
		});
	}

	patchSendButton() {
		const sendBtn = document.getElementById("sendButton");
		if (!sendBtn) return;

		sendBtn.onclick = (e) => {
			e.preventDefault();
			this.handleSend();
		};
	}

	handleSend() {
		// If processing, abort the current stream
		if (isProcessingMessage && currentAbortController) {
			console.log("Aborting current stream...");
			currentAbortController.abort();
			return;
		}

		if (isProcessingMessage) {
			console.log("Message already being processed, please wait...");
			return;
		}

		const input = document.getElementById("messageInput");
		const text = input.value.trim();

		if (this.isSending) {
			console.log("Already sending, please wait...");
			return;
		}

		isProcessingMessage = true;
		this.setSendButtonState("sending");

		if (this.currentMode === "generate") {
			this.handleImageGeneration(text);
		} else {
			// [UNIFIED] All normal chat and image messages now use sendMessageStreaming
			this.handleUnifiedMessage(text);
		}
	}

	async handleUnifiedMessage(text) {
		if (!text && this.selectedImages.length === 0) {
			isProcessingMessage = false;
			this.setSendButtonState("ready");
			return;
		}

		// Build a single unified message containing text + images for local history display
		let combinedMarkdown = "";
		if (text?.trim()) {
			combinedMarkdown += `${text.trim()}\n\n`;
		}

		const imageBlobs = [];
		this.selectedImages.forEach((image) => {
			const imageUrl = URL.createObjectURL(image);
			combinedMarkdown += `![Uploaded Image](${imageUrl})\n\n`;
			imageBlobs.push(image);
		});

		addMessage("user", combinedMarkdown.trim());
		this.clearInput();

		// Use streaming endpoint for real-time rendering of all message types
		await this.sendMessageStreaming(text, imageBlobs);

		this.clearImages();
		if (this.currentMode !== "chat") {
			this.switchMode("chat");
		}
	}

	async handleChatMessage(text) {
		// DEPRECATED: Unified into handleUnifiedMessage
		return this.handleUnifiedMessage(text);
	}

	async handleImageMessage(text) {
		// DEPRECATED: Unified into handleUnifiedMessage
		return this.handleUnifiedMessage(text);
	}

	async sendMessageStreaming(message, images = []) {
		const chatContainer = document.getElementById("chatContainer");

		if (!chatContainer) {
			console.error("Chat container not found");
			isProcessingMessage = false;
			this.setSendButtonState("ready");
			return;
		}

		// Create abort controller for this request
		currentAbortController = new AbortController();
		const signal = currentAbortController.signal;

		// Show typing indicator as in-flow message
		showTypingIndicator();

		// Create streaming message (hidden until first chunk - typing indicator still visible)
		// Create AI message element
		currentStreamMessage = this.createStreamingMessageElement("ai");
		currentStreamMessage.style.display = "none";
		chatContainer.appendChild(currentStreamMessage);

		const contentDiv = currentStreamMessage.querySelector(".message-content");
		let accumulatedText = "";

		try {
			let response;
			if (images && images.length > 0) {
				// Use FormData for images
				const formData = new FormData();
				formData.append("message", message || "");
				images.forEach((img) => {
					formData.append("images", img);
				});

				response = await fetch("/api/send_message_stream", {
					method: "POST",
					body: formData,
					signal,
				});
			} else {
				// Standard JSON for text-only
				response = await fetch("/api/send_message_stream", {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ message }),
					signal,
				});
			}

			if (!response.ok) {
				throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let firstChunk = true;
			let sseBuffer = ""; // [FIX] Tail-buffer nahan chunk yang kepotong

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				const chunk = decoder.decode(value, { stream: true });
				sseBuffer += chunk; // Masuk buffer
				const lines = sseBuffer.split("\n");
				sseBuffer = lines.pop(); // Tahan string yg belum komplit

				for (const line of lines) {
					if (line.startsWith("data: ")) {
						try {
							const json = JSON.parse(line.slice(6));
							if (json.chunk) {
								// Hide typing indicator and show message on first real content
								if (firstChunk) {
									hideTypingIndicator();
									currentStreamMessage.style.display = "";
									firstChunk = false;
								}

								// Immediately append and render - NO debounce
								accumulatedText += json.chunk;

								// Render immediately - real-time streaming
								// renderStreamChunk already does full markdown rendering
								this.renderStreamChunk(contentDiv, accumulatedText);
								scrollToBottom();

								// [UNIFIED] If the chunk contains the vision error message, handle it
								if (
									accumulatedText.includes(
										"[System] Current model does not support vision",
									)
								) {
									// It's a validation error, keep it in the stream
								}
							}
						} catch (_e) {
							// Ignore parse errors
						}
					}
				}
			}

			// Final processing after stream completes
			// Render final content with isComplete=true to ensure all mermaid blocks render
			this.renderStreamChunk(contentDiv, accumulatedText, true);

			// Update copy button handler with full content
			if (currentStreamMessage) {
				const copyBtn = currentStreamMessage.querySelector(".copy-message-btn");
				if (copyBtn) {
					copyBtn.onclick = () => {
						navigator.clipboard
							.writeText(accumulatedText)
							.then(() => {
								copyBtn.innerHTML = `
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <polyline points="20 6 9 17 4 12"></polyline>
                                </svg>
                            `;
								setTimeout(() => {
									copyBtn.innerHTML = `
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                    </svg>
                                `;
								}, 2000);
							})
							.catch((err) => console.error("Copy failed:", err));
					};
				}
			}
		} catch (error) {
			// Handle abort gracefully
			if (error.name === "AbortError") {
				console.log("Stream aborted by user");
				// Show partial message or remove it
				if (currentStreamMessage && !accumulatedText) {
					currentStreamMessage.remove();
				} else if (contentDiv && accumulatedText) {
					// Show partial response with indicator
					contentDiv.innerHTML = `${renderer.render(accumulatedText)}\n\n*[Stopped]*`;
					this.renderStreamChunk(contentDiv, accumulatedText, true);
				}
			} else {
				console.error("Stream error:", error);
				if (contentDiv) {
					contentDiv.textContent =
						"Sorry, I encountered an error processing your message.";
				}
			}
		} finally {
			hideTypingIndicator();
			this.cleanupStreamState();
			currentAbortController = null;
			isProcessingMessage = false;
			this.isSending = false;
			this.setSendButtonState("ready");
		}
	}

	renderStreamChunk(contentDiv, text, isComplete = false) {
		// For streaming: render markdown incrementally
		// Use streaming-aware render to handle incomplete mermaid blocks
		if (typeof renderer !== "undefined" && renderer.isMarkedReady) {
			// Use streaming render for incomplete, normal render for complete
			contentDiv.innerHTML = isComplete
				? renderer.render(text)
				: renderer.renderStreaming(text, true);

			// Initialize mermaid diagrams (placeholders are skipped automatically)
			if (renderer.isMermaidReady) {
				renderer.initializeMermaidDiagrams(contentDiv);
			}

			// Initialize table copy buttons during streaming
			if (typeof renderer !== "undefined") {
				renderer.initializeTableCopyButtons(contentDiv);
			}
		} else {
			// Fallback: just show raw text
			contentDiv.textContent = text;
		}
	}

	createStreamingMessageElement(role) {
		const msg = document.createElement("div");
		msg.className = `message ${role}`;
		msg.setAttribute("data-streaming", "true");

		// User messages use nested bubble structure: wrapper > bubble + footer
		// AI messages keep the original flat structure
		const isUserMessage = role === "user";

		if (isUserMessage) {
			// === USER MESSAGE: NESTED BUBBLE STRUCTURE ===
			const bubble = document.createElement("div");
			bubble.className = "message-bubble";

			const contentDiv = document.createElement("div");
			contentDiv.className = "message-content";
			bubble.appendChild(contentDiv);
			msg.appendChild(bubble);

			// Footer OUTSIDE the bubble
			const footer = document.createElement("div");
			footer.className = "message-footer message-footer--user";

			const timeDiv = document.createElement("div");
			timeDiv.className = "timestamp";
			timeDiv.textContent = this.getCurrentTime();
			footer.appendChild(timeDiv);

			const copyBtn = document.createElement("button");
			copyBtn.className = "copy-message-btn";
			copyBtn.title = "Copy full message";
			copyBtn.innerHTML = `
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
					<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
				</svg>
			`;
			footer.appendChild(copyBtn);

			msg.appendChild(footer);
			return msg;
		}

		// === AI MESSAGE: ORIGINAL FLAT STRUCTURE ===
		const contentDiv = document.createElement("div");
		contentDiv.className = "message-content";
		msg.appendChild(contentDiv);

		const footer = document.createElement("div");
		footer.className = "message-footer";

		const timeDiv = document.createElement("div");
		timeDiv.className = "timestamp";
		timeDiv.textContent = this.getCurrentTime();
		footer.appendChild(timeDiv);

		const copyBtn = document.createElement("button");
		copyBtn.className = "copy-message-btn";
		copyBtn.title = "Copy full message";
		copyBtn.innerHTML = `
			<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
				<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
			</svg>
		`;
		footer.appendChild(copyBtn);

		msg.appendChild(footer);
		return msg;
	}

	finalizeStreamMessage(contentDiv, finalContent) {
		if (!contentDiv) return;

		// Final render with full markdown processing
		contentDiv.innerHTML = renderer.render(finalContent);

		// Final highlight pass
		if (typeof hljs !== "undefined") {
			contentDiv.querySelectorAll("pre code:not(.hljs)").forEach((block) => {
				hljs.highlightElement(block);
			});
		}

		// Final mermaid initialization
		if (renderer.isMermaidReady) {
			renderer.initializeMermaidDiagrams(contentDiv);
		}

		// Update copy button handler
		if (currentStreamMessage) {
			const copyBtn = currentStreamMessage.querySelector(".copy-message-btn");
			if (copyBtn) {
				// Uses centralized copyFullMessage which internally uses ClipboardUtils
				copyBtn.onclick = () => copyFullMessage(finalContent);
			}
			currentStreamMessage.removeAttribute("data-streaming");
		}
	}

	cleanupStreamState() {
		currentStreamMessage = null;
	}

	async handleImageGeneration(prompt) {
		if (!prompt.trim()) {
			alert("Please enter a prompt for image generation");
			isProcessingMessage = false;
			return;
		}

		this.isSending = true;
		this.setSendButtonState("sending");

		try {
			console.log("Generating image with prompt:", prompt);

			addMessage("user", prompt);

			// Use dynamic typing indicator
			showTypingIndicator();

			// Use streaming endpoint for proper agentic loop support
			const response = await fetch("/api/send_message_stream", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ message: `/imagine ${prompt}` }),
			});

			if (!response.ok) {
				throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			}

			// Create streaming message element
			const chatContainer = document.getElementById("chat-container");
			currentStreamMessage = this.createStreamingMessageElement("ai");
			currentStreamMessage.style.display = "none";
			chatContainer.appendChild(currentStreamMessage);

			const contentDiv = currentStreamMessage.querySelector(".message-content");
			let accumulatedText = "";

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let firstChunk = true;
			let sseBuffer = ""; // [FIX] Tail-buffer nahan chunk yang kepotong

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				const chunk = decoder.decode(value, { stream: true });
				sseBuffer += chunk; // Masuk buffer
				const lines = sseBuffer.split("\n");
				sseBuffer = lines.pop(); // Tahan string yg belum komplit

				for (const line of lines) {
					if (line.startsWith("data: ")) {
						try {
							const json = JSON.parse(line.slice(6));
							if (json.chunk) {
								if (firstChunk) {
									hideTypingIndicator();
									currentStreamMessage.style.display = "";
									firstChunk = false;
								}

								accumulatedText += json.chunk;
								this.renderStreamChunk(contentDiv, accumulatedText);
								scrollToBottom();
							}
						} catch (_e) {
							// Ignore parse errors
						}
					}
				}
			}

			// Final render
			this.renderStreamChunk(contentDiv, accumulatedText, true);
			this.clearInput();
		} catch (error) {
			console.error("Image generation failed:", error);
			hideTypingIndicator();
			addMessage("ai", `Error: ${error.message}`);
		} finally {
			this.cleanupStreamState();
			this.isSending = false;
			this.setSendButtonState("ready");
			isProcessingMessage = false;
		}
	}

	displayGeneratedImage(imageUrl, _prompt) {
		const generatedMarkdown = /!\s*\[[^\]]*\]\s*\n?\s*\([^)]+\)/.test(
			String(imageUrl),
		)
			? String(imageUrl)
			: `![Generated Image](${imageUrl})`;
		addMessage("ai", generatedMarkdown);
	}

	displayUploadedImage(imageUrl, caption) {
		const uploadedMarkdown = caption
			? `![Uploaded Image](${imageUrl})\n\n${caption}`
			: `![Uploaded Image](${imageUrl})`;
		addMessage("user", uploadedMarkdown);
	}

	setSendButtonState(state) {
		const sendBtn = document.getElementById("sendButton");
		if (!sendBtn) return;

		if (state === "sending") {
			sendBtn.disabled = false; // Keep clickable for abort
			sendBtn.textContent = "Stop";
			sendBtn.classList.add("stop-mode");
			sendBtn.style.opacity = "1";
		} else {
			sendBtn.disabled = false;
			sendBtn.textContent = "Send";
			sendBtn.classList.remove("stop-mode");
			sendBtn.style.opacity = "1";
		}
	}

	getCurrentTime() {
		const now = new Date();
		return `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
	}

	downloadImage(imageUrl, filename) {
		const link = document.createElement("a");
		link.href = imageUrl;
		link.download = `${filename || "generated_image"}.png`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	regenerateImage(prompt) {
		const input = document.getElementById("messageInput");
		if (input) {
			input.value = prompt;
			this.switchMode("generate");
			setTimeout(() => this.handleImageGeneration(prompt), 100);
		}
	}

	toggleDropdown() {
		if (this.isDropdownOpen) {
			this.closeDropdown();
		} else {
			this.openDropdown();
		}
	}

	openDropdown() {
		this.closeDropdown();

		const dropdownHTML = `
            <div class="multimodal-dropdown">
                <div class="multimodal-option ${this.currentMode === "chat" ? "active" : ""}" data-mode="chat">
                    <div class="option-icon">${this.getSVGIcon("chat")}</div>
                    <div class="option-content">
                        <div class="option-text">Chat</div>
                        <div class="option-description">Normal chat</div>
                    </div>
                </div>
                <div class="multimodal-option ${this.currentMode === "generate" ? "active" : ""}" data-mode="generate">
                    <div class="option-icon">${this.getSVGIcon("generate")}</div>
                    <div class="option-content">
                        <div class="option-text">Generate Image</div>
                        <div class="option-description">Create images with AI</div>
                    </div>
                </div>
                <div class="multimodal-option ${this.currentMode === "image" ? "active" : ""}" data-mode="image">
                    <div class="option-icon">${this.getSVGIcon("image")}</div>
                    <div class="option-content">
                        <div class="option-text">Upload Image</div>
                        <div class="option-description">Upload + analyze images</div>
                    </div>
                </div>
                
                ${
									this.currentMode === "image"
										? `
                <div class="image-upload-area">
                    <div class="upload-placeholder">
                        ${this.selectedImages.length > 0 ? `${this.selectedImages.length} image(s) ready!` : "Upload images for analysis"}
                    </div>
                    <input type="file" id="imageUpload" accept="image/*" multiple style="display: none;">
                    <button class="upload-btn" onclick="multimodal.openFilePicker()">
                        ${this.getSVGIcon("upload")}
                        <span>${this.selectedImages.length > 0 ? "Add More Images" : "Choose Images"}</span>
                    </button>
                    ${this.selectedImages.length > 0 ? this.renderImagePreviews() : ""}
                </div>
                `
										: ""
								}
            </div>
        `;

		this.toggleBtn.insertAdjacentHTML("afterend", dropdownHTML);
		this.isDropdownOpen = true;

		const dropdown = this.toggleBtn.nextElementSibling;
		dropdown
			.querySelectorAll(".multimodal-option[data-mode]")
			.forEach((option) => {
				option.addEventListener("click", () => {
					const mode = option.dataset.mode;
					this.switchMode(mode);
					this.closeDropdown();
				});
			});

		if (this.currentMode === "image") {
			const fileInput = document.getElementById("imageUpload");
			fileInput.onchange = (e) => {
				if (e.target.files.length > 0) {
					this.addImages(Array.from(e.target.files));
					this.closeDropdown();
					setTimeout(() => this.openDropdown(), 100);
				}
			};
		}
	}

	renderImagePreviews() {
		if (this.selectedImages.length === 0) return "";

		const previews = this.selectedImages
			.map((image, index) => {
				const previewUrl = URL.createObjectURL(image);
				return `
                <div class="image-preview-container">
                    <img class="image-preview" src="${previewUrl}" alt="Preview ${index + 1}">
                    <button class="remove-image-btn" onclick="multimodal.removeImage(${index})" type="button">
                        ${this.getSVGIcon("close")}
                    </button>
                </div>
            `;
			})
			.join("");

		return `
            <div class="image-previews-header">
                <span>${this.selectedImages.length} image(s) ready</span>
                <button class="clear-all-btn" onclick="multimodal.clearImages()" type="button">Clear All</button>
            </div>
            <div class="image-previews-grid">
                ${previews}
            </div>
        `;
	}

	openFilePicker() {
		document.getElementById("imageUpload").click();
	}

	closeDropdown() {
		const dropdown = document.querySelector(".multimodal-dropdown");
		if (dropdown) dropdown.remove();
		this.isDropdownOpen = false;
	}

	switchMode(mode) {
		this.currentMode = mode;

		const indicators = { chat: "C", generate: "G", image: "U" };
		this.toggleBtn.querySelector(".toggle-icon").innerHTML =
			this.getSVGIcon(mode);
		this.modeIndicator.textContent = indicators[mode];

		if (mode === "image" && this.selectedImages.length > 0) {
			this.imageCountBadge.classList.remove("hidden");
		} else if (mode !== "image") {
			this.clearImages();
		}
	}

	addImages(files) {
		this.selectedImages.push(...files);
		this.updateNotificationCount();
	}

	removeImage(index) {
		this.selectedImages.splice(index, 1);
		this.updateNotificationCount();
		this.closeDropdown();
		if (this.currentMode === "image") {
			setTimeout(() => this.openDropdown(), 100);
		}
	}

	clearImages() {
		this.selectedImages = [];
		this.updateNotificationCount();
	}

	updateNotificationCount() {
		if (!this.imageCountBadge) return;

		if (this.selectedImages.length > 0) {
			this.imageCountBadge.textContent = this.selectedImages.length;
			this.imageCountBadge.classList.remove("hidden");
		} else {
			this.imageCountBadge.classList.add("hidden");
		}
	}

	clearInput() {
		const input = document.getElementById("messageInput");
		if (input) {
			input.value = "";
			input.style.height = "auto";
		}
	}
}

// ==================== SCROLL BUTTON FUNCTIONS ====================
function createScrollButton() {
	const scrollBtn = document.getElementById("scrollToBottomBtn");
	if (!scrollBtn) return;

	scrollBtn.onclick = scrollToBottom;
	initializeScrollButtonAutoHide();
}

function initializeScrollButtonAutoHide() {
	const chatContainer = document.getElementById("chatContainer");
	const scrollBtn = document.getElementById("scrollToBottomBtn");

	if (!chatContainer || !scrollBtn) return;

	function updateScrollButton() {
		const scrollHeight = chatContainer.scrollHeight;
		const scrollPosition = chatContainer.scrollTop + chatContainer.clientHeight;
		const scrollThreshold = 150;
		const distanceFromBottom = scrollHeight - scrollPosition;

		if (distanceFromBottom > scrollThreshold) {
			scrollBtn.classList.remove("hidden");
		} else {
			scrollBtn.classList.add("hidden");
		}
	}

	let scrollTimeout;
	function handleScroll() {
		if (!scrollTimeout) {
			scrollTimeout = setTimeout(() => {
				updateScrollButton();
				scrollTimeout = null;
			}, 50);
		}
	}

	chatContainer.addEventListener("scroll", handleScroll);
	window.addEventListener("resize", updateScrollButton);
	updateScrollButton();
}

// ==================== CHAT FUNCTIONS ====================
async function loadCurrentSessionName() {
	try {
		const response = await fetch("/api/get_profile");
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

function scrollToBottom() {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;

	// Use requestAnimationFrame to ensure scroll happens after layout calculations
	// This prevents race conditions when mermaid diagrams render asynchronously
	requestAnimationFrame(() => {
		chatContainer.scroll({
			top: chatContainer.scrollHeight,
			behavior: "smooth",
		});
	});

	const scrollBtn = document.getElementById("scrollToBottomBtn");
	if (scrollBtn) {
		scrollBtn.classList.add("hidden");
	}
}

function createMessageElement(role, content, timestamp = null) {
	const msg = document.createElement("div");
	msg.className = `message ${role}`;

	// User messages use nested bubble structure: wrapper > bubble + footer
	// AI messages keep the original flat structure for backward compatibility
	const isUserMessage = role === "user";

	// Format timestamp
	const displayTime = timestamp
		? formatTimestamp(timestamp)
		: getCurrentTime24h();

	if (isUserMessage) {
		// === USER MESSAGE: NESTED BUBBLE STRUCTURE ===
		// Outer wrapper contains bubble + footer stacked vertically
		// This keeps the colored background only on the text content

		// Bubble container - holds the colored background
		const bubble = document.createElement("div");
		bubble.className = "message-bubble";

		// Content inside the bubble
		const contentContainer = document.createElement("div");
		contentContainer.className = "message-content";

		// Render content through a single safe pipeline
		if (typeof renderer !== "undefined") {
			contentContainer.innerHTML = renderMessageContent(
				String(content),
				role === "user",
			);

			// Apply syntax highlighting to code blocks after rendering
			setTimeout(() => {
				if (typeof hljs !== "undefined") {
					const codeBlocks = contentContainer.querySelectorAll("pre code");
					codeBlocks.forEach((block) => {
						if (!block.classList.contains("hljs")) {
							hljs.highlightElement(block);
						}
					});
				}
			}, 0);
		} else {
			contentContainer.textContent = String(content);
		}

		bubble.appendChild(contentContainer);
		msg.appendChild(bubble);

		// Footer OUTSIDE the bubble (timestamp + copy button)
		const footer = document.createElement("div");
		footer.className = "message-footer message-footer--user";

		const timeDiv = document.createElement("div");
		timeDiv.className = "timestamp";
		timeDiv.textContent = displayTime;
		footer.appendChild(timeDiv);

		const copyBtn = document.createElement("button");
		copyBtn.className = "copy-message-btn";
		copyBtn.title = "Copy full message";
		copyBtn.innerHTML = `
			<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
				<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
			</svg>
		`;
		copyBtn.onclick = () => copyFullMessage(content);
		footer.appendChild(copyBtn);

		msg.appendChild(footer);
	} else {
		// === AI MESSAGE: ORIGINAL FLAT STRUCTURE ===
		// Kept for backward compatibility with existing CSS
		const contentContainer = document.createElement("div");
		contentContainer.className = "message-content";

		if (typeof renderer !== "undefined") {
			contentContainer.innerHTML = renderMessageContent(
				String(content),
				role === "user",
			);

			setTimeout(() => {
				if (typeof hljs !== "undefined") {
					const codeBlocks = contentContainer.querySelectorAll("pre code");
					codeBlocks.forEach((block) => {
						if (!block.classList.contains("hljs")) {
							hljs.highlightElement(block);
						}
					});
				}
			}, 0);
		} else {
			contentContainer.textContent = String(content);
		}

		msg.appendChild(contentContainer);

		const footer = document.createElement("div");
		footer.className = "message-footer";

		const timeDiv = document.createElement("div");
		timeDiv.className = "timestamp";
		timeDiv.textContent = displayTime;
		footer.appendChild(timeDiv);

		const copyBtn = document.createElement("button");
		copyBtn.className = "copy-message-btn";
		copyBtn.title = "Copy full message";
		copyBtn.innerHTML = `
			<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
				<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
			</svg>
		`;
		copyBtn.onclick = () => copyFullMessage(content);
		footer.appendChild(copyBtn);

		msg.appendChild(footer);
	}

	return msg;
}

function copyFullMessage(content) {
	// Uses centralized ClipboardUtils from renderer.js for consistent behavior
	if (typeof ClipboardUtils !== "undefined") {
		ClipboardUtils.copyText(content);
	} else {
		// Fallback for cases where renderer.js hasn't loaded
		navigator.clipboard
			.writeText(content)
			.then(() => {
				console.log("Message copied to clipboard");
			})
			.catch((err) => {
				console.error("Failed to copy message:", err);
			});
	}
}

function addMessage(role, content, timestamp = null, isHistory = false) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) {
		console.error("Cannot add message: chat container not found!");
		return null;
	}

	const msg = createMessageElement(role, content, timestamp);
	chatContainer.appendChild(msg);

	if (!isHistory) {
		setTimeout(() => {
			scrollToBottom();
			// Update layout after message append
			if (typeof window.updateDynamicLayout === "function") {
				window.updateDynamicLayout();
			}
		}, 50);
	}

	console.log(`Added ${role} message`);
	return msg;
}

function isRenderableHistoryRole(role) {
	return (
		role === "user" ||
		role === "assistant" ||
		(typeof role === "string" && role.endsWith("_tools"))
	);
}

function renderMessageContent(rawText, isUser = false) {
	const safeText = String(rawText ?? "");
	console.log("User raw message:", JSON.stringify(safeText));
	const escapedText = escapeMessageHtml(safeText);
	try {
		let processed = safeText;
		if (
			typeof renderer !== "undefined" &&
			typeof renderer.preprocessGeneratedImages === "function"
		) {
			processed = renderer.preprocessGeneratedImages(processed);
		}
		if (
			typeof renderer !== "undefined" &&
			typeof renderer.renderMessage === "function"
		) {
			return renderer.renderMessage(processed, isUser);
		}
		return escapedText;
	} catch (e) {
		console.error("Render error:", e, safeText);
		return `<pre class="render-error">${escapedText}</pre>`;
	}
}

function escapeMessageHtml(text) {
	if (
		typeof renderer !== "undefined" &&
		typeof renderer.escapeHtml === "function"
	) {
		return renderer.escapeHtml(text);
	}
	return String(text).replace(
		/[&<>"']/g,
		(c) =>
			({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
				c
			],
	);
}

function formatTimestamp(timestamp) {
	if (!timestamp) return "";

	try {
		const dbDate = new Date(timestamp);
		let hours = dbDate.getHours();
		let minutes = dbDate.getMinutes();

		hours = hours < 10 ? `0${hours}` : hours;
		minutes = minutes < 10 ? `0${minutes}` : minutes;

		return `${hours}:${minutes}`;
	} catch (e) {
		console.error("Error formatting timestamp:", e, timestamp);
		return timestamp;
	}
}

function getCurrentTime24h() {
	const now = new Date();
	let hours = now.getHours();
	let minutes = now.getMinutes();
	hours = hours < 10 ? `0${hours}` : hours;
	minutes = minutes < 10 ? `0${minutes}` : minutes;
	return `${hours}:${minutes}`;
}

// ==================== CHAT HISTORY WITH PAGINATION ====================
async function loadChatHistory(sessionId = null) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) {
		console.error("Cannot load history: chat container not found!");
		return;
	}

	try {
		// Show skeleton loading
		showChatSkeleton();
		setTimeout(scrollToBottom, 100);

		// Build URL with optional session ID
		const url = "/api/get_profile";
		if (sessionId) {
			// Fetch specific session's history
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
		const data = await res.json();
		const history = data.chat_history || [];

		// Hide skeleton before rendering real content
		hideChatSkeleton();

		if (history.length > 0) {
			chatContainer.innerHTML = "";
			console.log(`Processing ${history.length} messages from history`);

			// Load last 30 messages initially
			const messagesToShow = history.slice(-MESSAGES_PER_PAGE);

			const fragment = document.createDocumentFragment();

			messagesToShow.forEach((msg) => {
				if (isRenderableHistoryRole(msg.role)) {
					console.log("[History] Raw message before render:", {
						role: msg.role,
						preview: String(msg.content || "").slice(0, 200),
					});
					const msgElement = createMessageElement(
						msg.role === "user" ? "user" : "ai",
						msg.content,
						msg.timestamp,
					);
					fragment.appendChild(msgElement);
				}
			});

			chatContainer.appendChild(fragment);

			// Apply syntax highlighting to all code blocks after rendering
			setTimeout(() => {
				if (typeof hljs !== "undefined") {
					const codeBlocks = chatContainer.querySelectorAll(
						"pre code:not(.hljs)",
					);
					codeBlocks.forEach((block) => {
						hljs.highlightElement(block);
					});
				}
				// Initialize mermaid diagrams from history
				if (typeof renderer !== "undefined" && renderer.isMermaidReady) {
					renderer.initializeMermaidDiagrams(chatContainer);
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
		addMessage(
			"ai",
			"Hello! I'm your AI companion. Let's start a new conversation!",
		);
		scrollToBottom();
		// Update layout on error too
		if (typeof window.updateDynamicLayout === "function") {
			window.updateDynamicLayout();
		}
	}
}

function addScrollLoadListener(fullHistory) {
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

				messagesToLoad.forEach((msg) => {
					if (isRenderableHistoryRole(msg.role)) {
						console.log("[History] Raw lazy-loaded message before render:", {
							role: msg.role,
							preview: String(msg.content || "").slice(0, 200),
						});
						const msgElement = createMessageElement(
							msg.role === "user" ? "user" : "ai",
							msg.content,
							msg.timestamp,
						);
						fragment.appendChild(msgElement);
					}
				});

				chatContainer.insertBefore(fragment, chatContainer.firstChild);

				// Apply syntax highlighting to newly loaded messages
				setTimeout(() => {
					if (typeof hljs !== "undefined") {
						const newCodeBlocks = chatContainer.querySelectorAll(
							"pre code:not(.hljs)",
						);
						newCodeBlocks.forEach((block) => {
							hljs.highlightElement(block);
						});
					}

					// Initialize mermaid diagrams in newly loaded messages
					if (typeof renderer !== "undefined" && renderer.isMermaidReady) {
						const newMermaid = chatContainer.querySelectorAll(
							".mermaid:not([data-processed])",
						);
						if (newMermaid.length > 0) {
							renderer.initializeMermaidDiagrams(chatContainer);
						}
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

// ==================== INPUT BEHAVIOR ====================
function initializeInputBehavior() {
	const input = document.getElementById("messageInput");
	const scrollBtn = document.getElementById("scrollToBottomBtn");
	const chatContainer = document.getElementById("chatContainer");

	if (!input) return;

	// Function to update dynamic layout based on input area height
	function updateDynamicLayout() {
		const inputArea = input.closest(".input-area");
		if (!inputArea) return;

		const inputAreaHeight = inputArea.offsetHeight;

		// Update scroll button position (10px above input area)
		if (scrollBtn) {
			scrollBtn.style.bottom = `${inputAreaHeight + 10}px`;
		}

		// Update chat container padding-bottom dynamically
		// Header height ~48px, so top padding is ~4.8rem
		// Bottom padding should be: input area height + margin for last message visibility
		if (chatContainer) {
			const headerHeight = 48; // Approximate header height in px
			const bottomMargin = 60; // Extra margin for last message visibility (increased for safety)
			chatContainer.style.paddingTop = `${headerHeight + 8}px`;
			chatContainer.style.paddingBottom = `${inputAreaHeight + bottomMargin}px`;
		}
	}

	// Auto-resize textarea
	input.oninput = () => {
		input.style.height = "auto";
		input.style.height = `${Math.min(input.scrollHeight, 400)}px`;
		updateDynamicLayout();
	};

	// Initial layout update
	updateDynamicLayout();

	// Update on window resize
	window.addEventListener("resize", updateDynamicLayout);

	// Use ResizeObserver for reliable input area height detection
	const inputArea = input.closest(".input-area");
	if (inputArea && typeof ResizeObserver !== "undefined") {
		const resizeObserver = new ResizeObserver(() => {
			updateDynamicLayout();
		});
		resizeObserver.observe(inputArea);

		// Also observe the input itself for height changes
		resizeObserver.observe(input);
	}

	// Expose globally for post-history and post-message updates
	window.updateDynamicLayout = updateDynamicLayout;
}

// ==================== INITIALIZATION ====================
function initializeChat() {
	console.log("Initializing clean chat system...");

	// Initialize scroll button
	createScrollButton();

	// Initialize input behavior
	initializeInputBehavior();

	// Initialize URL router
	const urlSessionId = router.initFromURL();

	// Load session name
	loadCurrentSessionName();

	// Load history - use URL session if available
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

// ==================== TYPING INDICATOR (in-flow message) ====================
let _typingIndicatorElement = null;
let _typingIndicatorShownAt = 0;
const TYPING_INDICATOR_MIN_DURATION_MS = 300;

function showTypingIndicator() {
	// Remove any existing indicator
	hideTypingIndicator(true);

	// Ensure layout is up-to-date before showing indicator
	if (typeof window.updateDynamicLayout === "function") {
		window.updateDynamicLayout();
	}

	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return null;

	const msg = document.createElement("div");
	msg.className = "message ai typing-indicator-message";
	msg.id = "typingIndicatorMessage";

	const dots = document.createElement("div");
	dots.className = "typing-dots";
	dots.innerHTML = "<span></span><span></span><span></span>";
	msg.appendChild(dots);

	chatContainer.appendChild(msg);
	_typingIndicatorElement = msg;
	_typingIndicatorShownAt = Date.now();

	scrollToBottom();
	return msg;
}

function hideTypingIndicator(force = false) {
	if (!_typingIndicatorElement) return;

	const elapsed = Date.now() - _typingIndicatorShownAt;
	const remaining = TYPING_INDICATOR_MIN_DURATION_MS - elapsed;

	if (force || remaining <= 0) {
		_typingIndicatorElement.remove();
		_typingIndicatorElement = null;
	} else {
		// Ensure minimum visibility
		setTimeout(() => {
			if (_typingIndicatorElement) {
				_typingIndicatorElement.remove();
				_typingIndicatorElement = null;
			}
		}, remaining);
	}
}

/**
 * Handle session switch from URL or sidebar.
 * @param {number} sessionId - Target session ID
 * @param {boolean} updateURL - Whether to update browser URL (default: true)
 */
async function handleSessionSwitch(sessionId, updateURL = true) {
	console.log(`[Chat] Switching to session ${sessionId}`);

	// Check for active stream in current session
	if (isProcessingMessage && currentAbortController) {
		const currentSession = router.currentSessionId;
		if (currentSession && backgroundStreams.hasActiveStream(currentSession)) {
			// Pause stream instead of canceling
			backgroundStreams.pauseStream(currentSession);
		}
	}

	// Check if target session has a paused stream
	if (backgroundStreams.hasActiveStream(sessionId)) {
		const chatContainer = document.getElementById("chatContainer");
		const stream = backgroundStreams.resumeStream(sessionId, chatContainer);

		if (stream) {
			// Re-attach to current streaming state
			currentStreamMessage = stream.messageElement;
			currentAbortController = stream.controller;
			// Don't reload history, just continue the stream
			if (updateURL) {
				router.updateURL(sessionId);
			}
			return;
		}
	}

	// Normal session switch: reload history
	if (updateURL) {
		router.updateURL(sessionId);
	}

	await loadChatHistory(sessionId);
}

// Start when page loads
window.onload = () => {
	initializeChat();
};

// Global exports
window.addMessage = addMessage;
window.scrollToBottom = scrollToBottom;
window.copyFullMessage = copyFullMessage;
window.loadChatHistory = loadChatHistory;
window.handleSessionSwitch = handleSessionSwitch;
window.router = router;
window.backgroundStreams = backgroundStreams;
