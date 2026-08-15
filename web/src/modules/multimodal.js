// FILE: static/js/modules/multimodal.js
// DESCRIPTION: Multimodal manager for image upload, generation, and streaming

import { renderRuntimeIcon } from "../runtime-icon-renderer.js";
import { apiFetch } from "./apiFetch.js";
import { eventRouter } from "./event-router.js";
import { router } from "./router.js";
import { isProcessingMessage, setIsProcessingMessage } from "./state.js";
import { chatStore } from "./store.js";

function waitForPaint() {
	return new Promise((resolve) => {
		if (typeof requestAnimationFrame !== "undefined") {
			requestAnimationFrame(() => requestAnimationFrame(resolve));
		} else {
			// Two-step setTimeout fallback when requestAnimationFrame is unavailable
			setTimeout(() => setTimeout(resolve, 0), 0);
		}
	});
}

/**
 * MultimodalManager handles chat modes, image upload, and streaming.
 */
export class MultimodalManager {
	constructor(modelInfo = null) {
		this.currentMode = "chat";
		this.modelInfo = modelInfo;
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
		const iconName = mode === "regenerate" ? "refresh" : mode;
		return (
			renderRuntimeIcon(iconName, {
				size:
					mode === "close"
						? 14
						: mode === "download" || mode === "upload" || mode === "copy"
							? 16
							: 20,
				strokeWidth: mode === "copy" ? 2 : 0,
			}) || ""
		);
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
			await waitForPaint();

			const formData = new FormData();
			formData.append("message", message);
			const clientTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
			const now = new Date();
			const offsetMinutes = -now.getTimezoneOffset();
			const sign = offsetMinutes >= 0 ? "+" : "-";
			const offset = `${sign}${String(Math.floor(Math.abs(offsetMinutes) / 60)).padStart(2, "0")}:${String(Math.abs(offsetMinutes) % 60).padStart(2, "0")}`;
			const clientLocalTime = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}T${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}.${String(now.getMilliseconds()).padStart(3, "0")}${offset}`;
			images.forEach((blob) => {
				formData.append("images", blob);
			});

			const response = await apiFetch("/api/v1/send_message_stream", {
				method: "POST",
				headers: {
					Accept: "text/event-stream",
					"X-Client-Timezone": clientTimezone,
					"X-Client-Local-Time": clientLocalTime,
				},
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

			eventRouter.finishStream(sessionId);
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
		dummy.className = "streaming-message-placeholder";
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
		} else {
			sendBtn.disabled = false;
			sendBtn.innerHTML =
				renderRuntimeIcon("send", {
					size: 20,
					strokeWidth: 2.5,
				}) || "";
			sendBtn.classList.remove("stop-mode");
		}
	}

	canUse(capability) {
		return this.modelInfo?.capabilities?.[capability] !== "unsupported";
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
                <div class="multimodal-option ${this.currentMode === "generate" ? "active" : ""} ${this.canUse("image_generation") ? "" : "disabled"}" data-mode="generate" aria-disabled="${!this.canUse("image_generation")}">
                    <div class="option-icon">${this.getSVGIcon("generate")}</div>
                    <div class="option-content">
                        <div class="option-text">Generate Image</div>
                        <div class="option-description">${this.canUse("image_generation") ? "Create images with AI" : "Current model does not declare image generation"}</div>
                    </div>
                </div>
                <div class="multimodal-option ${this.currentMode === "image" ? "active" : ""} ${this.canUse("vision") ? "" : "disabled"}" data-mode="image" aria-disabled="${!this.canUse("vision")}">
                    <div class="option-icon">${this.getSVGIcon("image")}</div>
                    <div class="option-content">
                        <div class="option-text">Upload Image</div>
                        <div class="option-description">${this.canUse("vision") ? "Upload + analyze images" : "Current model does not declare vision"}</div>
                    </div>
                </div>
                ${
									this.currentMode === "image" && this.canUse("vision")
										? `
                <div class="image-upload-area">
                    <div class="upload-placeholder">
                        ${this.selectedImages.length > 0 ? `${this.selectedImages.length} image(s) ready!` : "Upload images for analysis"}
                    </div>
                    <input type="file" id="imageUpload" class="visually-hidden-input" accept="image/*" multiple data-multimodal-action="select-images">
                    <button class="upload-btn" data-multimodal-action="open-file-picker" type="button">
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
		dropdown.addEventListener("click", (event) => {
			const action = event.target.closest("[data-multimodal-action]");
			if (!action) return;
			switch (action.dataset.multimodalAction) {
				case "open-file-picker":
					if (this.canUse("vision")) this.openFilePicker();
					break;
				case "remove-image":
					this.removeImage(Number(action.dataset.imageIndex));
					break;
				case "clear-images":
					this.clearImages();
					break;
			}
		});
		dropdown
			.querySelectorAll(".multimodal-option[data-mode]")
			.forEach((option) => {
				option.addEventListener("click", () => {
					const mode = option.dataset.mode;
					if (mode === "image" && !this.canUse("vision")) return;
					if (mode === "generate" && !this.canUse("image_generation")) return;
					this.switchMode(mode);
					this.closeDropdown();
				});
			});

		if (this.currentMode === "image") {
			const fileInput = document.getElementById("imageUpload");
			fileInput.addEventListener("change", (e) => {
				if (e.target.files.length > 0) {
					this.addImages(Array.from(e.target.files));
					this.closeDropdown();
					setTimeout(() => this.openDropdown(), 100);
				}
			});
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
                    <button class="remove-image-btn" data-multimodal-action="remove-image" data-image-index="${index}" type="button">
                        ${this.getSVGIcon("close")}
                    </button>
                </div>
            `;
			})
			.join("");

		return `
            <div class="image-previews-header">
                <span>${this.selectedImages.length} image(s) ready</span>
                <button class="clear-all-btn" data-multimodal-action="clear-images" type="button">Clear All</button>
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
