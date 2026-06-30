// FILE: static/js/modules/multimodal.js
// DESCRIPTION: Multimodal manager for image upload, generation, and streaming

import { captureDetailsState, restoreDetailsState } from "./dom-utils.js";
import { addMessage } from "./messages.js";
import { router } from "./router.js";
import { scrollToBottom } from "./scroll.js";
import {
	currentAbortController,
	currentStreamMessage,
	generateMessageId,
	isProcessingMessage,
	setCurrentAbortController,
	setCurrentStreamMessage,
	setIsProcessingMessage,
} from "./state.js";
import { backgroundStreams } from "./stream-manager.js";
import {
	hideTypingIndicator,
	showTypingIndicator,
} from "./typing-indicator.js";

/**
 * MultimodalManager handles chat modes, image upload, and streaming.
 */
export class MultimodalManager {
	constructor() {
		this.currentMode = "chat";
		this.visualMode = false;
		this.selectedImages = [];
		this.isDropdownOpen = false;
		this.isSending = false;
		this.toggleBtn = null;
		this.modeIndicator = null;
		this.imageCountBadge = null;
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

		setIsProcessingMessage(true);
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
			setIsProcessingMessage(false);
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

	async sendMessageStreaming(message, images = []) {
		try {
			const chatContainer = document.getElementById("chatContainer");

			if (!chatContainer) {
				console.error("Chat container not found");
				setIsProcessingMessage(false);
				this.setSendButtonState("ready");
				return;
			}

			// [CRITICAL] Get session ID and validate it
			const sessionId = router.currentSessionId;

			// GUARD: Prevent streaming without valid session
			if (!sessionId || sessionId === "null" || sessionId === "undefined") {
				console.error(
					"[Multimodal] Cannot send message: Invalid session ID",
					sessionId,
				);
				setIsProcessingMessage(false);
				this.setSendButtonState("ready");
				return;
			}

			backgroundStreams.setActiveView(sessionId);

			// [FIX] Check if there's already an active stream for this session
			// This prevents duplicate bubbles on page reload mid-generation
			const existingStream = backgroundStreams.getStream(sessionId);
			if (existingStream?.isActive) {
				console.log(
					`[Stream] Resuming existing stream for session ${sessionId}`,
				);
				// Find existing message element
				const existingElement = document.querySelector(
					`[data-message-id="${existingStream.messageId}"]`,
				);
				if (existingElement) {
					setCurrentStreamMessage(existingElement);
					// Flush existing buffer
					this.renderStreamChunk(
						currentStreamMessage.querySelector(".message-content"),
						existingStream.buffer,
					);
				} else {
					// Create new element with the same ID
					setCurrentStreamMessage(
						this.createStreamingMessageElement("ai", existingStream.messageId),
					);
					chatContainer.appendChild(currentStreamMessage);
					this.renderStreamChunk(
						currentStreamMessage.querySelector(".message-content"),
						existingStream.buffer,
					);
				}
				// Don't start a new fetch, the existing SSE reader is still running
				return;
			}

			// [FIX] Generate message ID for tracking
			const messageId = generateMessageId();

			// Create abort controller for this request
			const abortController = new AbortController();
			setCurrentAbortController(abortController);

			// Register stream with background manager BEFORE starting fetch
			backgroundStreams.startStream(sessionId, abortController, messageId);

			// Show typing indicator as in-flow message
			showTypingIndicator();

			// Create streaming message element with unique ID
			setCurrentStreamMessage(
				this.createStreamingMessageElement("ai", messageId),
			);
			currentStreamMessage.style.display = "none";
			chatContainer.appendChild(currentStreamMessage);

			// [DOM REBIND FIX] Store messageId, look up contentDiv dynamically
			// This prevents stale references when DOM is rebuilt
			let localBuffer = ""; // Local buffer for this stream instance

			const formData = new FormData();
			formData.append("message", message);
			images.forEach((blob) => {
				formData.append("images", blob);
			});

			const response = await fetch("/api/send_message_stream", {
				method: "POST",
				body: formData,
				signal: abortController.signal,
			});

			if (!response.ok) {
				throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let firstChunk = true;
			let sseBuffer = "";

			while (true) {
				const { done, value } = await reader.read();

				if (done) {
					// Stream complete
					backgroundStreams.completeStream(sessionId);
					break;
				}

				const chunk = decoder.decode(value, { stream: true });
				sseBuffer += chunk;
				const lines = sseBuffer.split("\n");
				sseBuffer = lines.pop();

				for (const line of lines) {
					if (line.startsWith("data: ")) {
						try {
							const json = JSON.parse(line.slice(6));
							// Typed event envelope (FC5+): type=token|tool_call|tool_result|done
							const eventType = json.type || null;
							const textChunk = json.chunk || null;

							if (eventType === "done") {
								// Turn complete — handled by stream completion below
								continue;
							}

							if (eventType === "tool_call" || eventType === "tool_result") {
								// Structured tool lifecycle event (FC6)
								const turnId = json.turn_id || json.data?.turn_id || "";
								if (sessionId === backgroundStreams.activeViewSessionId) {
									const contentDiv = this._getContentDivForMessage(messageId);
									if (contentDiv) {
										if (eventType === "tool_call") {
											const toolName = json.data?.name || "unknown";
											const callId = json.data?.id || "";
											console.log(`[Stream] tool_call: ${toolName} [call=${callId} turn=${turnId}]`);
											// Append tool call indicator to buffer
											const callHtml = `\n<details class="tool-call-indicator"><summary>⚙️ Calling ${toolName}…</summary><pre data-call-id="${callId}">Waiting for result…</pre></details>\n`;
											localBuffer += callHtml;
											backgroundStreams.appendChunk(sessionId, callHtml);
											this.renderStreamChunk(contentDiv, backgroundStreams.getBuffer(sessionId));
										} else if (eventType === "tool_result") {
											const toolName = json.data?.name || "unknown";
											const callId = json.data?.call_id || "";
											const ok = json.data?.ok ?? true;
											const resultMarkdown = json.data?.markdown || "";
											console.log(`[Stream] tool_result: ${toolName} ok=${ok} [call=${callId} turn=${turnId}]`);
											// Update or append result
											const statusIcon = ok ? "✅" : "❌";
											const resultHtml = `\n<details class="tool-result" open><summary>${statusIcon} ${toolName}</summary><div class="tool-result-content">${resultMarkdown}</div></details>\n`;
											localBuffer += resultHtml;
											backgroundStreams.appendChunk(sessionId, resultHtml);
											this.renderStreamChunk(contentDiv, backgroundStreams.getBuffer(sessionId));
											// Update matching call indicator to show completed
											const callPre = contentDiv.querySelector(`pre[data-call-id="${callId}"]`);
											if (callPre) callPre.textContent = "Completed ✓";
										}
										scrollToBottom();
									}
								}
								continue;
							}

							if (textChunk) {
								// [CRITICAL] ALWAYS buffer to BackgroundStreamManager
								// This happens regardless of which session is currently active
								localBuffer += json.chunk;
								backgroundStreams.appendChunk(sessionId, json.chunk);

								// [CRITICAL] Only update DOM if this session is the active view
								if (sessionId === backgroundStreams.activeViewSessionId) {
									// [DOM REBIND FIX] Look up contentDiv dynamically by messageId
									const contentDiv = this._getContentDivForMessage(messageId);
									if (contentDiv) {
										if (firstChunk) {
											hideTypingIndicator();
											const msgEl = contentDiv.closest(".message");
											if (msgEl) msgEl.style.display = "";
											firstChunk = false;
										}
										this.renderStreamChunk(
											contentDiv,
											backgroundStreams.getBuffer(sessionId),
										);
										scrollToBottom();
									}
								} else {
									console.log(
										`[Stream] Session ${sessionId} buffering in background (${localBuffer.length} chars)`,
									);
								}
							}
						} catch (_e) {
							// Ignore parse errors
						}
					}
				}
			}

			// Final render with isComplete=true
			if (sessionId === backgroundStreams.activeViewSessionId) {
				const contentDiv = this._getContentDivForMessage(messageId);
				if (contentDiv) {
					this.renderStreamChunk(contentDiv, localBuffer, true);
				}
			}

			this.clearInput();
		} catch (error) {
			if (error.name === "AbortError") {
				console.log("Stream aborted by user");
			} else {
				console.error("Stream error:", error);
				hideTypingIndicator();
				addMessage("ai", `Error: ${error.message}`);
			}
			const sessionId = router?.currentSessionId;
			if (sessionId) {
				backgroundStreams.cancelStream(sessionId);
			}
		} finally {
			this.cleanupStreamState();
			this.setSendButtonState("ready");
			setIsProcessingMessage(false);
		}
	}

	_getContentDivForMessage(messageId) {
		if (!messageId) return null;
		const msgEl = document.querySelector(`[data-message-id="${messageId}"]`);
		return msgEl?.querySelector(".message-content") || null;
	}

	renderStreamChunk(contentDiv, text, isComplete = false) {
		// [ACCORDION PRESERVATION] Capture current <details> open states (index-based)
		const detailsStates = captureDetailsState(contentDiv);

		// For streaming: render markdown incrementally
		// Use streaming-aware render to handle incomplete mermaid blocks
		if (typeof renderer !== "undefined" && renderer.isMarkedReady) {
			// Use streaming render for incomplete, normal render for complete
			contentDiv.innerHTML = isComplete
				? renderer.render(text)
				: renderer.renderStreaming(text, true);

			// [ACCORDION PRESERVATION] Restore <details> open states after innerHTML update
			restoreDetailsState(contentDiv, detailsStates);

			// Initialize mermaid diagrams with DEBOUNCE during streaming
			// This prevents UI freeze from synchronous mermaid.run() on every chunk
			if (renderer.isMermaidReady) {
				renderer.initializeMermaidDiagrams(contentDiv, !isComplete);
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

	createStreamingMessageElement(role, messageId = null) {
		const msg = document.createElement("div");
		msg.className = `message ${role}`;
		msg.setAttribute("data-streaming", "true");

		// [CRITICAL] Set message ID for DOM tracking
		if (messageId) {
			msg.setAttribute("data-message-id", messageId);
		} else {
			msg.setAttribute("data-message-id", generateMessageId());
		}

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
		copyBtn.setAttribute("data-action", "copy-message");
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

	cleanupStreamState() {
		setCurrentStreamMessage(null);
		// Note: Session tracking is handled by BackgroundStreamManager.activeViewSessionId
		// Don't clear currentAbortController - it's tracked by BackgroundStreamManager
	}

	async handleImageGeneration(prompt) {
		if (!prompt.trim()) {
			alert("Please enter a prompt for image generation");
			setIsProcessingMessage(false);
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
			const chatContainer = document.getElementById("chatContainer");
			setCurrentStreamMessage(this.createStreamingMessageElement("ai"));
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
							// Typed event envelope (FC5+)
							const eventType = json.type || null;
							const textChunk = json.chunk || null;

							if (eventType === "done") continue;
							if (eventType === "tool_call" || eventType === "tool_result") {
								// Render tool events inline (FC6)
								if (eventType === "tool_call") {
									const toolName = json.data?.name || "unknown";
									accumulatedText += `\n<details class="tool-call-indicator"><summary>⚙️ Calling ${toolName}…</summary></details>\n`;
								} else if (eventType === "tool_result") {
									const toolName = json.data?.name || "unknown";
									const ok = json.data?.ok ?? true;
									const statusIcon = ok ? "✅" : "❌";
									accumulatedText += `\n<details class="tool-result" open><summary>${statusIcon} ${toolName}</summary><div class="tool-result-content">${json.data?.markdown || ""}</div></details>\n`;
									this.renderStreamChunk(contentDiv, accumulatedText);
								}
								continue;
							}

							if (textChunk) {
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
			setIsProcessingMessage(false);
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
