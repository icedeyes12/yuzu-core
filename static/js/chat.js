// [FILE: chat.js] - OPTIMIZED VERSION
// [VERSION: 1.0.0.69.6] - PERFORMANCE OPTIMIZED
// [DATE: 2025-08-12]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: Optimized chat interface with performance improvements]
// [AUTHOR: Project Lead: Bani Baskara]
// [TEAM: Deepseek, GPT, Qwen, Aihara]
// [REPOSITORY: https://github.com/icedeyes12]
// [LICENSE: MIT]

console.log("Starting OPTIMIZED chat with performance improvements...");

// ==================== PERFORMANCE OPTIMIZATIONS ====================
let isProcessingMessage = false; // Global flag to prevent double-send

// ==================== MULTIMODAL MANAGER ====================
class MultimodalManager {
    constructor() {
        this.currentMode = 'chat';
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
        const inputArea = document.querySelector('.input-area');
        if (!inputArea) return;

        if (inputArea.querySelector('.multimodal-toggle-container')) return;

        const toggleHTML = `
            <div class="multimodal-toggle-container">
                <button class="multimodal-toggle-btn" type="button" title="Multimodal Mode">
                    <span class="toggle-icon">${this.getSVGIcon('chat')}</span>
                    <div class="mode-indicator">C</div>
                    <div class="image-count-badge hidden">0</div>
                </button>
            </div>
        `;
        
        inputArea.insertAdjacentHTML('afterbegin', toggleHTML);
        this.toggleBtn = inputArea.querySelector('.multimodal-toggle-btn');
        this.modeIndicator = inputArea.querySelector('.mode-indicator');
        this.imageCountBadge = inputArea.querySelector('.image-count-badge');
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
                   </svg>`
        };
        return icons[mode] || icons.chat;
    }

    setupEventListeners() {
        if (!this.toggleBtn) return;
        
        this.toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleDropdown();
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.multimodal-toggle-container')) {
                this.closeDropdown();
            }
        });
    }

    patchSendButton() {
        const sendBtn = document.getElementById('sendButton');
        if (!sendBtn) return;

        sendBtn.onclick = (e) => {
            e.preventDefault();
            this.handleSend();
        };
    }

    handleSend() {
        // PREVENTION: Check global flag to prevent double-send
        if (isProcessingMessage) {
            console.log("Message already being processed, please wait...");
            return;
        }

        const input = document.getElementById('messageInput');
        const text = input.value.trim();

        if (this.isSending) {
            console.log("Already sending, please wait...");
            return;
        }

        // SET GLOBAL FLAG
        isProcessingMessage = true;

        if (this.currentMode === 'generate') {
            this.handleImageGeneration(text);
        } else if (this.currentMode === 'image' || this.selectedImages.length > 0) {
            this.handleImageMessage(text);
        } else {
            this.handleChatMessage(text);
        }
    }

    async handleChatMessage(text) {
        if (!text) {
            isProcessingMessage = false;
            return;
        }

        addMessage("user", text);
        this.clearInput();
        
        if (typingIndicator) typingIndicator.classList.remove("hidden");

        try {
            const response = await fetch("/api/send_message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text }),
            });
            
            const data = await response.json();
            
            if (typingIndicator) typingIndicator.classList.add("hidden");
            
            if (data.reply) {
                addMessage("ai", data.reply);
            } else {
                addMessage("ai", "No response from server");
            }
        } catch (error) {
            console.error("Error sending message:", error);
            if (typingIndicator) typingIndicator.classList.add("hidden");
            addMessage("ai", "Connection error. Please try again.");
        } finally {
            // RESET GLOBAL FLAG
            isProcessingMessage = false;
            this.isSending = false;
        }
    }

    async handleImageGeneration(prompt) {
        if (!prompt.trim()) {
            alert('Please enter a prompt for image generation');
            isProcessingMessage = false;
            return;
        }

        this.isSending = true;
        this.setSendButtonState('sending');

        try {
            console.log("Generating image with prompt:", prompt);
            
            addMessage("user", prompt);
            
            const response = await fetch("/api/generate_image", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt })
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                this.displayGeneratedImage(data.image_url, prompt);
                this.clearInput();
            } else {
                throw new Error(data.error || 'Image generation failed');
            }
            
        } catch (error) {
            console.error('Image generation failed:', error);
            addMessage("ai", `Error: ${error.message}`);
        } finally {
            this.isSending = false;
            this.setSendButtonState('ready');
            isProcessingMessage = false;
        }
    }

    async handleImageMessage(text) {
        if (!text && this.selectedImages.length === 0) {
            alert('Please enter a message or upload images');
            isProcessingMessage = false;
            return;
        }

        this.isSending = true;
        this.setSendButtonState('sending');

        try {
            addMessage("user", text || "Analyze these images");
            
            this.selectedImages.forEach((image) => {
                const imageUrl = URL.createObjectURL(image);
                this.displayUploadedImage(imageUrl, text);
            });

            const formData = new FormData();
            if (text) formData.append('message', text);
            
            this.selectedImages.forEach((image) => {
                formData.append('images', image);
            });

            const response = await fetch("/api/send_message_with_images", {
                method: "POST",
                body: formData
            });
            
            const data = await response.json();
            
            if (data.reply) {
                addMessage("ai", data.reply);
                this.clearInput();
                this.clearImages();
                
                if (this.currentMode !== 'chat') {
                    this.switchMode('chat');
                }
            } else {
                throw new Error(data?.error || 'Image processing failed');
            }
            
        } catch (error) {
            console.error('Image message failed:', error);
            addMessage("ai", `Error: ${error.message}`);
        } finally {
            this.isSending = false;
            this.setSendButtonState('ready');
            isProcessingMessage = false;
        }
    }

    displayUploadedImage(imageUrl, caption = '') {
        const chatContainer = document.getElementById('chatContainer');
        if (!chatContainer) return;

        const imageHTML = `
            <div class="message user uploaded-image-message">
                <div class="message-content">
                    ${caption ? `<div class="image-caption">${this.escapeHtml(caption)}</div>` : ''}
                    <div class="uploaded-image-container">
                        <img src="${imageUrl}" alt="Uploaded image" class="uploaded-image">
                    </div>
                    <div class="timestamp">${this.getCurrentTime()}</div>
                </div>
            </div>
        `;
        
        chatContainer.insertAdjacentHTML('beforeend', imageHTML);
        scrollToBottom();
    }

    displayGeneratedImage(imageUrl, prompt) {
        const chatContainer = document.getElementById('chatContainer');
        if (!chatContainer) return;

        if (imageUrl.startsWith('generated_images/')) {
            imageUrl = `/static/${imageUrl}`;
        }

        const imageHTML = `
            <div class="message user generated-image-message">
                <div class="message-content">
                    <div class="image-prompt-text">${this.escapeHtml(prompt)}</div>
                    <div class="generated-image-container">
                        <img src="${imageUrl}" alt="${prompt}" class="generated-image">
                        <div class="image-actions">
                            <button class="image-action-btn" onclick="multimodal.downloadImage('${imageUrl}', '${prompt.replace(/[^a-z0-9]/gi, '_')}')">
                                ${this.getSVGIcon('download')}
                                <span>Download</span>
                            </button>
                            <button class="image-action-btn" onclick="multimodal.regenerateImage('${prompt}')">
                                ${this.getSVGIcon('regenerate')}
                                <span>Regenerate</span>
                            </button>
                        </div>
                    </div>
                    <div class="timestamp">${this.getCurrentTime()}</div>
                </div>
            </div>
        `;
        
        chatContainer.insertAdjacentHTML('beforeend', imageHTML);
        
        const aiResponseHTML = `
            <div class="message ai">
                <div class="message-content">
                    Image generated successfully! I've created your "${prompt}" 
                    <div class="timestamp">${this.getCurrentTime()}</div>
                </div>
            </div>
        `;
        chatContainer.insertAdjacentHTML('beforeend', aiResponseHTML);
        
        scrollToBottom();
    }

    updateNotificationCount() {
        if (!this.imageCountBadge) return;
        
        const count = this.selectedImages.length;
        
        if (count > 0) {
            this.imageCountBadge.textContent = count;
            this.imageCountBadge.classList.remove('hidden');
            
            this.imageCountBadge.classList.add('pulse');
            setTimeout(() => {
                this.imageCountBadge.classList.remove('pulse');
            }, 1000);
        } else {
            this.imageCountBadge.classList.add('hidden');
        }
    }

    addImages(files) {
        this.selectedImages = [...this.selectedImages, ...files];
        this.updateNotificationCount();
        
        if (this.currentMode === 'image') {
            this.updateInputPlaceholder();
        }
    }

    removeImage(index) {
        this.selectedImages.splice(index, 1);
        this.updateNotificationCount();
        
        this.closeDropdown();
        setTimeout(() => this.openDropdown(), 100);
    }

    clearImages() {
        this.selectedImages = [];
        this.updateNotificationCount();
        
        if (this.isDropdownOpen && this.currentMode === 'image') {
            this.closeDropdown();
            setTimeout(() => this.openDropdown(), 100);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clearInput() {
        const input = document.getElementById('messageInput');
        if (input) {
            input.value = '';
            input.style.height = 'auto';
            this.updateInputPlaceholder();
        }
    }

    setSendButtonState(state) {
        const sendBtn = document.getElementById('sendButton');
        if (!sendBtn) return;

        if (state === 'sending') {
            sendBtn.disabled = true;
            sendBtn.textContent = 'Sending...';
            sendBtn.style.opacity = '0.7';
        } else {
            sendBtn.disabled = false;
            sendBtn.textContent = 'Send';
            sendBtn.style.opacity = '1';
        }
    }

    getCurrentTime() {
        const now = new Date();
        return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
    }

    downloadImage(imageUrl, filename) {
        const link = document.createElement('a');
        link.href = imageUrl;
        link.download = `${filename || 'generated_image'}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    regenerateImage(prompt) {
        const input = document.getElementById('messageInput');
        if (input) {
            input.value = prompt;
            this.switchMode('generate');
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
                <div class="multimodal-option ${this.currentMode === 'chat' ? 'active' : ''}" data-mode="chat">
                    <div class="option-icon">${this.getSVGIcon('chat')}</div>
                    <div class="option-content">
                        <div class="option-text">Chat</div>
                        <div class="option-description">Normal chat</div>
                    </div>
                </div>
                <div class="multimodal-option ${this.currentMode === 'generate' ? 'active' : ''}" data-mode="generate">
                    <div class="option-icon">${this.getSVGIcon('generate')}</div>
                    <div class="option-content">
                        <div class="option-text">Generate Image</div>
                        <div class="option-description">Create images with AI</div>
                    </div>
                </div>
                <div class="multimodal-option ${this.currentMode === 'image' ? 'active' : ''}" data-mode="image">
                    <div class="option-icon">${this.getSVGIcon('image')}</div>
                    <div class="option-content">
                        <div class="option-text">Upload Image</div>
                        <div class="option-description">Upload + analyze images</div>
                    </div>
                </div>
                
                ${this.currentMode === 'image' ? `
                <div class="image-upload-area">
                    <div class="upload-placeholder">
                        ${this.selectedImages.length > 0 ? `${this.selectedImages.length} image(s) ready!` : 'Upload images for analysis'}
                    </div>
                    <input type="file" id="imageUpload" accept="image/*" multiple style="display: none;">
                    <button class="upload-btn" onclick="multimodal.openFilePicker()">
                        ${this.getSVGIcon('upload')}
                        <span>${this.selectedImages.length > 0 ? 'Add More Images' : 'Choose Images'}</span>
                    </button>
                    ${this.selectedImages.length > 0 ? this.renderImagePreviews() : ''}
                </div>
                ` : ''}
            </div>
        `;

        this.toggleBtn.insertAdjacentHTML('afterend', dropdownHTML);
        this.isDropdownOpen = true;

        const dropdown = this.toggleBtn.nextElementSibling;
        dropdown.querySelectorAll('.multimodal-option').forEach(option => {
            option.addEventListener('click', () => {
                const mode = option.dataset.mode;
                this.switchMode(mode);
                this.closeDropdown();
            });
        });

        if (this.currentMode === 'image') {
            const fileInput = document.getElementById('imageUpload');
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
        if (this.selectedImages.length === 0) return '';
        
        const previews = this.selectedImages.map((image, index) => {
            const previewUrl = URL.createObjectURL(image);
            return `
                <div class="image-preview-container">
                    <img class="image-preview" src="${previewUrl}" alt="Preview ${index + 1}">
                    <button class="remove-image-btn" onclick="multimodal.removeImage(${index})" type="button">
                        ${this.getSVGIcon('close')}
                    </button>
                </div>
            `;
        }).join('');

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
        document.getElementById('imageUpload').click();
    }

    closeDropdown() {
        const dropdown = document.querySelector('.multimodal-dropdown');
        if (dropdown) dropdown.remove();
        this.isDropdownOpen = false;
    }

    switchMode(mode) {
        this.currentMode = mode;
        
        const indicators = { chat: 'C', generate: 'G', image: 'U' };
        this.toggleBtn.querySelector('.toggle-icon').innerHTML = this.getSVGIcon(mode);
        this.modeIndicator.textContent = indicators[mode];
        
        if (mode === 'image' && this.selectedImages.length > 0) {
            this.imageCountBadge.classList.remove('hidden');
        } else if (mode !== 'image') {
            this.imageCountBadge.classList.add('hidden');
        }
        
        this.updateInputPlaceholder();
    }

    updateInputPlaceholder() {
        const input = document.getElementById('messageInput');
        if (!input) return;
        
        const placeholders = {
            chat: 'Type your message...',
            generate: 'Describe the image to generate...',
            image: this.selectedImages.length > 0 
                ? `Ask about ${this.selectedImages.length} image(s)...`
                : 'Upload images first...'
        };
        
        input.placeholder = placeholders[this.currentMode];
    }
}

// ==================== OPTIMIZED SCROLL SYSTEM ====================
function createPermanentScrollButton() {
    const existingBtn = document.getElementById("scrollToBottom");
    if (existingBtn) existingBtn.remove();
    
    const btn = document.createElement("button");
    btn.id = "scrollToBottom";
    btn.title = "Scroll to bottom";
    btn.innerHTML = "↓";
    btn.classList.add("hidden");
    btn.onclick = scrollToBottom;
    
    document.body.appendChild(btn);
    console.log("Scroll button created");
    return btn;
}

function initializeScrollButtonAutoHide() {
    const chatContainer = document.getElementById("chatContainer");
    const scrollBtn = document.getElementById("scrollToBottom");
    
    if (!chatContainer || !scrollBtn) return;
    
    function updateScrollButton() {
        const scrollThreshold = 150;
        const scrollPosition = chatContainer.scrollTop + chatContainer.clientHeight;
        const scrollHeight = chatContainer.scrollHeight;
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
    
    chatContainer.addEventListener('scroll', handleScroll);
    window.addEventListener('resize', updateScrollButton);
    updateScrollButton();
}

function monitorScrollSystem() {
    const chatContainer = document.getElementById("chatContainer");
    const scrollBtn = document.getElementById("scrollToBottom");
    
    if (!chatContainer) {
        console.error("Chat container not found!");
        return false;
    }
    
    if (!scrollBtn) {
        createPermanentScrollButton();
        initializeScrollButtonAutoHide();
        return false;
    }
    
    return true;
}

// ==================== OPTIMIZED CHAT FUNCTIONS ====================
async function loadCurrentSessionName() {
    try {
        const response = await fetch('/api/get_profile');
        const data = await response.json();
        
        const sessionNameElement = document.getElementById('sessionName');
        if (sessionNameElement && data.active_session) {
            sessionNameElement.textContent = data.active_session.name || 'Current Chat';
        }
    } catch (error) {
        console.error('Failed to load session name:', error);
    }
}

function scrollToBottom() {
    const chatContainer = document.getElementById("chatContainer");
    if (!chatContainer) {
        console.error("Chat container not found!");
        return;
    }
    
    // OPTIMIZED: Use smooth scroll with performance consideration
    chatContainer.scroll({
        top: chatContainer.scrollHeight,
        behavior: 'smooth'
    });
    
    const scrollBtn = document.getElementById("scrollToBottom");
    if (scrollBtn) {
        scrollBtn.classList.add("hidden");
    }
}

function createMessageElement(role, content, timestamp = null) {
    const msg = document.createElement("div");
    msg.classList.add("message", role);
    
    const displayTime = timestamp ? formatTimestamp(timestamp) : getCurrentTime24h();

    const contentContainer = document.createElement("div");

    if (typeof renderMessageContent !== 'undefined') {
        contentContainer.innerHTML = renderMessageContent(String(content));
    } else if (typeof MarkdownParser !== 'undefined') {
        contentContainer.innerHTML = MarkdownParser.parseWithEmojis(String(content));
    } else {
        contentContainer.textContent = String(content);
    }

    const timeDiv = document.createElement("div");
    timeDiv.className = "timestamp";
    timeDiv.textContent = displayTime;
    contentContainer.appendChild(timeDiv);

    msg.appendChild(contentContainer);
    return msg;
}

// OPTIMIZED: New function to process only new elements
function processNewMessageElement(element) {
    if (!element) return;
    
    // Highlight code blocks only in this new element
    if (typeof MarkdownParser !== 'undefined' && typeof MarkdownParser.highlightNewElement === 'function') {
        MarkdownParser.highlightNewElement(element);
    }
    
    // Initialize copy buttons only in this new element
    initializeCopyButtons(element);
}

function addMessage(role, content, timestamp = null, isHistory = false) {
    const chatContainer = document.getElementById("chatContainer");
    if (!chatContainer) {
        console.error("Cannot add message: chat container not found!");
        return null;
    }
    
    const msg = createMessageElement(role, content, timestamp);
    chatContainer.appendChild(msg);
    
    // OPTIMIZED: Only process new elements for real-time messages, not history
    if (!isHistory) {
        processNewMessageElement(msg);
        
        setTimeout(() => {
            scrollToBottom();
        }, 50);
    }
    
    console.log(`Added ${role} message`);
    return msg;
}

function formatTimestamp(timestamp) {
    if (!timestamp) return '';
    
    try {
        const dbDate = new Date(timestamp);
        let hours = dbDate.getHours();
        let minutes = dbDate.getMinutes();
        
        hours = hours < 10 ? '0' + hours : hours;
        minutes = minutes < 10 ? '0' + minutes : minutes;
        
        return `${hours}:${minutes}`;
    } catch (e) {
        console.error('Error formatting timestamp:', e, timestamp);
        return timestamp;
    }
}

function getCurrentTime24h() {
    const now = new Date();
    let hours = now.getHours();
    let minutes = now.getMinutes();
    hours = hours < 10 ? '0' + hours : hours;
    minutes = minutes < 10 ? '0' + minutes : minutes;
    return `${hours}:${minutes}`;
}

// ==================== OPTIMIZED HISTORY FUNCTION ====================
async function loadChatHistory() {
    const chatContainer = document.getElementById("chatContainer");
    if (!chatContainer) {
        console.error("Cannot load history: chat container not found!");
        return;
    }
    
    try {
        chatContainer.innerHTML = '<div class="loading">Loading recent messages...</div>';
        setTimeout(scrollToBottom, 100);
        
        const res = await fetch("/api/get_profile");
        const data = await res.json();
        const history = data.chat_history || [];

        if (history.length > 0) {
            chatContainer.innerHTML = '';
            console.log(`Processing ${history.length} messages from history`);
            
            const immediateDisplayCount = Math.min(30, history.length);
            const messagesToShowImmediately = history.slice(-immediateDisplayCount);
            
            // OPTIMIZED: Use document fragment for batch DOM operations
            const fragment = document.createDocumentFragment();
            
            messagesToShowImmediately.forEach(msg => {
                if (msg.role === "user" || msg.role === "assistant") {
                    const msgElement = createMessageElement(
                        msg.role === "user" ? "user" : "ai", 
                        msg.content, 
                        msg.timestamp
                    );
                    fragment.appendChild(msgElement);
                }
            });
            
            chatContainer.appendChild(fragment);
            
            // OPTIMIZED: Process all history messages at once after DOM insertion
            setTimeout(() => {
                if (typeof MarkdownParser !== 'undefined') {
                    MarkdownParser.highlightCodeBlocks(chatContainer);
                }
                initializeCopyButtons(chatContainer);
                scrollToBottom();
                
                if (history.length > immediateDisplayCount) {
                    setTimeout(() => loadOlderMessages(history, immediateDisplayCount), 500);
                }
            }, 300);
            
            console.log(`Immediately displayed ${messagesToShowImmediately.length} recent messages`);
        } else {
            console.log("No chat history found");
            addMessage("ai", "Hello! I'm your AI companion. Let's start a new conversation!");
            scrollToBottom();
        }
    } catch (err) {
        console.error("Failed to load chat history:", err);
        addMessage("ai", "Hello! I'm your AI companion. Let's start a new conversation!");
        scrollToBottom();
    }
}

async function loadOlderMessages(fullHistory, alreadyLoadedCount) {
    const chatContainer = document.getElementById("chatContainer");
    if (!chatContainer) return;
    
    const olderMessages = fullHistory.slice(0, -alreadyLoadedCount);
    const totalOlder = olderMessages.length;
    
    if (totalOlder === 0) return;
    
    console.log(`Loading ${totalOlder} older messages in background...`);
    
    const loadingIndicator = document.createElement('div');
    loadingIndicator.className = 'loading-older';
    loadingIndicator.innerHTML = `<div class="loading-spinner-small"></div> Loading ${totalOlder} older messages...`;
    chatContainer.insertBefore(loadingIndicator, chatContainer.firstChild);
    
    await new Promise(resolve => setTimeout(resolve, 100));
    
    const fragment = document.createDocumentFragment();
    
    olderMessages.forEach(msg => {
        if (msg.role === "user" || msg.role === "assistant") {
            const msgElement = createMessageElement(
                msg.role === "user" ? "user" : "ai", 
                msg.content, 
                msg.timestamp
            );
            fragment.appendChild(msgElement);
        }
    });
    
    if (loadingIndicator.parentNode) {
        loadingIndicator.parentNode.removeChild(loadingIndicator);
    }
    
    if (chatContainer.firstChild) {
        chatContainer.insertBefore(fragment, chatContainer.firstChild);
    } else {
        chatContainer.appendChild(fragment);
    }
    
    // OPTIMIZED: Process older messages in a single batch
    setTimeout(() => {
        if (typeof MarkdownParser !== 'undefined') {
            MarkdownParser.highlightCodeBlocks(chatContainer);
        }
        initializeCopyButtons(chatContainer);
    }, 100);
    
    console.log(`Loaded ${totalOlder} older messages in background`);
}

// ==================== OPTIMIZED COPY FUNCTIONS ====================
function initializeCopyButtons(parentElement = document) {
    // OPTIMIZED: Only search within the specified parent element
    const codeContainers = parentElement.querySelectorAll('.code-block-container');
    
    codeContainers.forEach(container => {
        // Check if copy button already exists to avoid duplicates
        const existingButton = container.querySelector('.copy-code-btn');
        if (existingButton) {
            return;
        }
        
        const copyButton = document.createElement('button');
        copyButton.className = 'copy-code-btn';
        copyButton.innerHTML = '<span class="copy-text">Copy</span>';
        
        copyButton.onclick = function() { 
            copyCodeToClipboard(this); 
        };
        
        const codeHeader = container.querySelector('.code-header');
        if (codeHeader) {
            codeHeader.appendChild(copyButton);
        }
    });
}

function copyCodeToClipboard(button) {
    const codeBlock = button.closest('.code-block-container');
    const codeElement = codeBlock.querySelector('code');
    const textToCopy = codeElement.textContent;
    
    navigator.clipboard.writeText(textToCopy).then(() => {
        const copyText = button.querySelector('.copy-text') || button;
        const originalText = copyText.textContent;
        
        if (button.querySelector('.copy-text')) {
            copyText.textContent = 'Copied!';
        } else {
            button.innerHTML = 'Copied!';
        }
        
        button.classList.add('copied');
        
        setTimeout(() => {
            if (button.querySelector('.copy-text')) {
                copyText.textContent = originalText;
            } else {
                button.innerHTML = 'Copy';
            }
            button.classList.remove('copied');
        }, 2000);
    }).catch(err => {
        console.error('Copy failed:', err);
    });
}

// ==================== OPTIMIZED HIGHLIGHT.JS INIT ====================
function initializeHighlightJS(container = document) {
    if (typeof hljs !== 'undefined') {
        // OPTIMIZED: Only process elements within the specified container
        const blocks = container.querySelectorAll('pre code');
        blocks.forEach((block) => {
            hljs.highlightElement(block);
        });
        console.log(`Highlight.js initialized on ${blocks.length} blocks`);
    } else {
        console.log("Highlight.js not loaded yet");
    }
}

// ==================== OPTIMIZED INPUT BEHAVIOR ====================
function initializeInputBehavior() {
    const input = document.getElementById('messageInput');
    if (!input) return;

    // Hanya auto-resize - Enter = new line (natural mobile behavior)
    input.oninput = () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 400) + 'px';
    };

    // Mobile-friendly: Enter = new line, Send button = send");
}

// ==================== OPTIMIZED INITIALIZATION ====================
function initializeChat() {
    console.log("Initializing OPTIMIZED chat system...");
    
    // Initialize scroll system
    createPermanentScrollButton();
    initializeScrollButtonAutoHide();
    
    // Initialize input behavior
    initializeInputBehavior();
    
    // Load session name
    loadCurrentSessionName();
    
    // Load history
    loadChatHistory();
    
    // Initialize multimodal
    window.multimodal = new MultimodalManager();
    window.multimodal.init();
    
    // Monitor scroll system
    setTimeout(() => monitorScrollSystem(), 1000);
    
    console.log("OPTIMIZED chat system ready!");
}

// Start when page loads
window.onload = function() {
    initializeChat();
};

// Global exports
window.addMessage = addMessage;
window.scrollToBottom = scrollToBottom;
window.copyCodeToClipboard = copyCodeToClipboard;
window.monitorScrollSystem = monitorScrollSystem;
window.loadChatHistory = loadChatHistory;
window.initializeHighlightJS = initializeHighlightJS;
window.initializeCopyButtons = initializeCopyButtons;
window.MultimodalManager = MultimodalManager;