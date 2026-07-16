// FILE: static/js/modules/multimodal.js
// DESCRIPTION: Multimodal manager for image upload, generation, and streaming

import { eventRouter } from "./event-router.js";
import { router } from "./router.js";
import { isProcessingMessage, setIsProcessingMessage } from "./state.js";
import { chatStore } from "./store.js";

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
		this.activeRequestId = 0;
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
			void this.handleSend();
		};
	}

	handleSend() {
		if (isProcessingMessage) {
			eventRouter.cancelStream(router.currentSessionId);
			this.setSendButtonState("ready");
			setIsProcessingMessage(false);
			return;
		}

		const input = document.getElementById("messageInput");
		const text = input.value.trim();

		if (this.isSending) {
			console.log("Already sending, please wait...");
			return;
		}

		this.isSending = true;
		setIsProcessingMessage(true);
		this.setSendButtonState("sending");

		if (this.currentMode === "generate") {
			void this.handleImageGeneration(text);
		} else {
			void this.handleUnifiedMessage(text);
		}
	}

	async handleUnifiedMessage(text) {
		const sessionId = router.currentSessionId;
		if (!sessionId) {
			chatStore.setError(
				"Cannot send a message without an active conversation.",
			);
			setIsProcessingMessage(false);
			this.setSendButtonState("ready");
			return;
		}

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

		chatStore.appendMessage({ role: "user", content: combinedMarkdown.trim() });
		this.clearInput();

		// Use streaming endpoint for real-time rendering of all message types
		await this.sendMessageStreaming(text, imageBlobs);

		this.clearImages();
		if (this.currentMode !== "chat") {
			this.switchMode("chat");
		}
	}

	async sendMessageStreaming(message, images = []) {
		let sessionId = null;
		let abortController = null;
		const requestId = ++this.activeRequestId;
		try {
			const chatContainer = document.getElementById("chatContainer");
			if (!chatContainer) {
				chatStore.setError("Chat container is unavailable.");
				setIsProcessingMessage(false);
				this.setSendButtonState("ready");
				return;
			}

			// [CRITICAL] Get session ID and validate it
			sessionId = router.currentSessionId;
			if (!sessionId || sessionId === "null" || sessionId === "undefined") {
				chatStore.setError(
					"Cannot send a message without an active conversation.",
				);
				setIsProcessingMessage(false);
				this.setSendButtonState("ready");
				return;
			}

			eventRouter.setActiveView(sessionId);
			chatStore.beginAssistantMessage();
			abortController = new AbortController();
			eventRouter.registerStream(sessionId, abortController);

			const formData = new FormData();
			formData.append("message", message);
			images.forEach((blob) => {
				formData.append("images", blob);
			});

			const response = await fetch("/api/send_message_stream", {
				method: "POST",
				headers: { Accept: "text/event-stream" },
				body: formData,
				signal: abortController.signal,
			});

			if (!response.ok) {
				throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			}
			if (!response.body) throw new Error("Streaming response has no body.");

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let sseBuffer = ""; // [FIX] Tail-buffer nahan chunk yang kepotong

			while (true) {
				const { done, value } = await reader.read();

				if (done) {
					sseBuffer += decoder.decode();
					break;
				}

				const chunk = decoder.decode(value, { stream: true });
				sseBuffer += chunk;
				const lines = sseBuffer.split("\n");
				sseBuffer = lines.pop();

				for (const line of lines) {
					if (line.startsWith("data: ")) {
						eventRouter.handleEvent(sessionId, line.substring(6));
					}
				}
			}
			if (sseBuffer.trim()) {
				const finalLine = sseBuffer.trim();
				if (finalLine.startsWith("data: ")) {
					eventRouter.handleEvent(sessionId, finalLine.substring(6));
				}
			}

			this.clearInput();
		} catch (error) {
			if (error.name === "AbortError") {
				if (requestId === this.activeRequestId) chatStore.finishGeneration();
			} else {
				chatStore.setError(error.message || "The message stream failed.");
			}
		} finally {
			if (
				requestId === this.activeRequestId &&
				sessionId &&
				eventRouter.controllers.get(sessionId) === abortController
			) {
				eventRouter.cancelStream(sessionId);
			}
			if (requestId === this.activeRequestId) {
				this.isSending = false;
				this.cleanupStreamState();
				this.setSendButtonState("ready");
				setIsProcessingMessage(false);
			}
		}
	}

	getContentContainer(messageId) {
		const msgEl = document.querySelector(`[data-message-id="${messageId}"]`);
		return msgEl?.querySelector(".message-content") || null;
	}

	renderStreamChunk(_contentDiv, _text, _isComplete = false) {
		// [ACCORDION PRESERVATION] Capture current <details> open states (index-based)
		// DELETED: DOM is no longer the source of truth, ConversationStore is.
		// DOMRenderer handles all updates now.
		// This method is a no-op shim until multimodal.js is fully stripped.
		return;
	}

	createStreamingMessageElement(_role, _messageId = null) {
		// DELETED: Store and DOMRenderer handle all message element creation now.
		// Returns a dummy element to prevent crashes in un-migrated legacy callers.
		const dummy = document.createElement("div");
		dummy.style.display = "none";
		return dummy;
	}

	cleanupStreamState() {
		// Store and EventRouter own active stream state.
	}

	async handleImageGeneration(prompt) {
		if (!prompt.trim()) {
			chatStore.setError("Please enter a prompt for image generation.");
			setIsProcessingMessage(false);
			this.setSendButtonState("ready");
			return;
		}
		chatStore.appendMessage({ role: "user", content: prompt.trim() });
		await this.sendMessageStreaming(`/imagine ${prompt.trim()}`);
	}

	displayGeneratedImage(imageUrl, _prompt) {
		const generatedMarkdown = /!\s*\[[^\]]*\]\s*\n?\s*\([^)]+\)/.test(
			String(imageUrl),
		)
			? String(imageUrl)
			: `![Generated Image](${imageUrl})`;
		chatStore.appendMessage({ role: "assistant", content: generatedMarkdown });
	}

	displayUploadedImage(imageUrl, caption) {
		const uploadedMarkdown = caption
			? `![Uploaded Image](${imageUrl})\n\n${caption}`
			: `![Uploaded Image](${imageUrl})`;
		chatStore.appendMessage({ role: "user", content: uploadedMarkdown });
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
			sendBtn.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;
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
