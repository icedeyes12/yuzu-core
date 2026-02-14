// [FILE: chat.js - Rebuilt Clean Version]
// [VERSION: 2.0.0]
// [DATE: 2026-02-14]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: Clean chat interface rebuilt for stability]
// [AUTHOR: Project Lead: Bani Baskara]

console.log("Starting clean chat rebuild...");

// ==================== GLOBAL STATE ====================
let isProcessingMessage = false;
let currentPage = 0;
const MESSAGES_PER_PAGE = 30;

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
        if (!inputArea || inputArea.querySelector('.multimodal-toggle-container')) return;

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
                   </svg>`,
            copy: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
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
        
        const typingIndicator = document.getElementById('typingIndicator');
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
                throw new Error(data.error || 'Failed to send message');
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

    displayGeneratedImage(imageUrl, prompt) {
        const chatContainer = document.getElementById('chatContainer');
        if (!chatContainer) return;

        const imageDiv = document.createElement('div');
        imageDiv.className = 'message ai generated-image-message';
        imageDiv.innerHTML = `
            <div class="generated-image-container">
                <img src="${imageUrl}" alt="Generated: ${prompt}" class="generated-image">
                <div class="image-actions">
                    <button class="image-action-btn" onclick="multimodal.downloadImage('${imageUrl}', 'generated-${Date.now()}')">
                        ${this.getSVGIcon('download')}
                        Download
                    </button>
                    <button class="image-action-btn" onclick="multimodal.regenerateImage('${prompt.replace(/'/g, "\\'")}')">
                        ${this.getSVGIcon('regenerate')}
                        Regenerate
                    </button>
                </div>
            </div>
            <div class="timestamp">${this.getCurrentTime()}</div>
        `;
        
        chatContainer.appendChild(imageDiv);
        scrollToBottom();
    }

    displayUploadedImage(imageUrl, caption) {
        const chatContainer = document.getElementById('chatContainer');
        if (!chatContainer) return;

        const imageDiv = document.createElement('div');
        imageDiv.className = 'message user uploaded-image-message';
        imageDiv.innerHTML = `
            <div class="uploaded-image-container">
                <img src="${imageUrl}" alt="Uploaded image" class="uploaded-image">
                ${caption ? `<div class="image-caption">${caption}</div>` : ''}
            </div>
            <div class="timestamp">${this.getCurrentTime()}</div>
        `;
        
        chatContainer.appendChild(imageDiv);
        scrollToBottom();
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
        if (this.currentMode === 'image') {
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
            this.imageCountBadge.classList.remove('hidden');
        } else {
            this.imageCountBadge.classList.add('hidden');
        }
    }

    clearInput() {
        const input = document.getElementById('messageInput');
        if (input) {
            input.value = '';
            input.style.height = 'auto';
        }
    }
}

// ==================== SCROLL BUTTON FUNCTIONS ====================
function createScrollButton() {
    const scrollBtn = document.getElementById('scrollToBottomBtn');
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
    
    chatContainer.addEventListener('scroll', handleScroll);
    window.addEventListener('resize', updateScrollButton);
    updateScrollButton();
}

// ==================== CHAT FUNCTIONS ====================
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
    if (!chatContainer) return;
    
    chatContainer.scroll({
        top: chatContainer.scrollHeight,
        behavior: 'smooth'
    });
    
    const scrollBtn = document.getElementById("scrollToBottomBtn");
    if (scrollBtn) {
        scrollBtn.classList.add("hidden");
    }
}

function createMessageElement(role, content, timestamp = null) {
    const msg = document.createElement("div");
    msg.classList.add("message", role);
    
    const displayTime = timestamp ? formatTimestamp(timestamp) : getCurrentTime24h();

    // Message content container
    const contentContainer = document.createElement("div");
    contentContainer.className = "message-content";

    // Render content using renderer
    if (role === "ai" && typeof renderer !== 'undefined') {
        contentContainer.innerHTML = renderer.renderMessage(String(content), false);
        
        // Apply syntax highlighting to code blocks after rendering
        setTimeout(() => {
            if (typeof hljs !== 'undefined') {
                const codeBlocks = contentContainer.querySelectorAll('pre code');
                codeBlocks.forEach(block => {
                    // Only highlight if not already highlighted
                    if (!block.classList.contains('hljs')) {
                        hljs.highlightElement(block);
                    }
                });
            }
        }, 0);
    } else {
        contentContainer.textContent = String(content);
    }

    msg.appendChild(contentContainer);

    // Create footer for timestamp and copy button
    const footer = document.createElement("div");
    footer.className = "message-footer";

    // Timestamp
    const timeDiv = document.createElement("div");
    timeDiv.className = "timestamp";
    timeDiv.textContent = displayTime;
    footer.appendChild(timeDiv);

    // Add copy button for assistant messages
    if (role === "ai") {
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
    }

    msg.appendChild(footer);
    
    return msg;
}

function copyFullMessage(content) {
    navigator.clipboard.writeText(content).then(() => {
        console.log('Message copied to clipboard');
    }).catch(err => {
        console.error('Failed to copy message:', err);
    });
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

// ==================== CHAT HISTORY WITH PAGINATION ====================
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
            
            // Load last 30 messages initially
            const messagesToShow = history.slice(-MESSAGES_PER_PAGE);
            
            const fragment = document.createDocumentFragment();
            
            messagesToShow.forEach(msg => {
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
            
            // Apply syntax highlighting to all code blocks after rendering
            setTimeout(() => {
                if (typeof hljs !== 'undefined') {
                    const codeBlocks = chatContainer.querySelectorAll('pre code:not(.hljs)');
                    codeBlocks.forEach(block => {
                        hljs.highlightElement(block);
                    });
                }
                scrollToBottom();
            }, 100);
            
            // Add scroll event for loading older messages
            if (history.length > MESSAGES_PER_PAGE) {
                addScrollLoadListener(history);
            }
            
            console.log(`Displayed ${messagesToShow.length} recent messages`);
        } else {
            console.log("No chat history found");
            chatContainer.innerHTML = '';
            addMessage("ai", "Hello! I'm your AI companion. Let's start a new conversation!");
            scrollToBottom();
        }
    } catch (err) {
        console.error("Failed to load chat history:", err);
        chatContainer.innerHTML = '';
        addMessage("ai", "Hello! I'm your AI companion. Let's start a new conversation!");
        scrollToBottom();
    }
}

function addScrollLoadListener(fullHistory) {
    const chatContainer = document.getElementById("chatContainer");
    if (!chatContainer) return;

    let isLoadingOlder = false;
    let olderMessagesLoaded = 0;

    chatContainer.addEventListener('scroll', async () => {
        if (isLoadingOlder) return;

        // Check if scrolled to top
        if (chatContainer.scrollTop < 100) {
            const remainingMessages = fullHistory.length - MESSAGES_PER_PAGE - olderMessagesLoaded;
            
            if (remainingMessages > 0) {
                isLoadingOlder = true;
                
                const loadCount = Math.min(MESSAGES_PER_PAGE, remainingMessages);
                const startIndex = fullHistory.length - MESSAGES_PER_PAGE - olderMessagesLoaded - loadCount;
                const messagesToLoad = fullHistory.slice(startIndex, startIndex + loadCount);
                
                console.log(`Loading ${loadCount} older messages...`);
                
                // Save scroll position
                const scrollHeightBefore = chatContainer.scrollHeight;
                
                const fragment = document.createDocumentFragment();
                
                messagesToLoad.forEach(msg => {
                    if (msg.role === "user" || msg.role === "assistant") {
                        const msgElement = createMessageElement(
                            msg.role === "user" ? "user" : "ai", 
                            msg.content, 
                            msg.timestamp
                        );
                        fragment.appendChild(msgElement);
                    }
                });
                
                chatContainer.insertBefore(fragment, chatContainer.firstChild);
                
                // Apply syntax highlighting to newly loaded messages
                setTimeout(() => {
                    if (typeof hljs !== 'undefined') {
                        const newCodeBlocks = chatContainer.querySelectorAll('pre code:not(.hljs)');
                        newCodeBlocks.forEach(block => {
                            hljs.highlightElement(block);
                        });
                    }
                }, 0);
                
                // Restore scroll position
                const scrollHeightAfter = chatContainer.scrollHeight;
                chatContainer.scrollTop = scrollHeightAfter - scrollHeightBefore;
                
                olderMessagesLoaded += loadCount;
                isLoadingOlder = false;
                
                console.log(`Loaded ${loadCount} older messages. Total loaded: ${MESSAGES_PER_PAGE + olderMessagesLoaded}`);
            }
        }
    });
}

// ==================== INPUT BEHAVIOR ====================
function initializeInputBehavior() {
    const input = document.getElementById('messageInput');
    const scrollBtn = document.getElementById('scrollToBottomBtn');
    
    if (!input) return;

    // Function to update scroll button position based on input area height
    function updateScrollButtonPosition() {
        if (scrollBtn) {
            const inputArea = input.closest('.input-area');
            if (inputArea) {
                const inputAreaHeight = inputArea.offsetHeight;
                // Position scroll button 10px above the input area
                scrollBtn.style.bottom = `${inputAreaHeight + 10}px`;
            }
        }
    }

    // Auto-resize textarea and update scroll button position
    input.oninput = () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 400) + 'px';
        updateScrollButtonPosition();
    };
    
    // Initial position update
    updateScrollButtonPosition();
    
    // Update on window resize
    window.addEventListener('resize', updateScrollButtonPosition);
}

// ==================== INITIALIZATION ====================
function initializeChat() {
    console.log("Initializing clean chat system...");
    
    // Initialize scroll button
    createScrollButton();
    
    // Initialize input behavior
    initializeInputBehavior();
    
    // Load session name
    loadCurrentSessionName();
    
    // Load history
    loadChatHistory();
    
    // Initialize multimodal
    window.multimodal = new MultimodalManager();
    window.multimodal.init();
    
    console.log("Clean chat system ready!");
}

// Start when page loads
window.onload = function() {
    initializeChat();
};

// Global exports
window.addMessage = addMessage;
window.scrollToBottom = scrollToBottom;
window.copyFullMessage = copyFullMessage;
window.loadChatHistory = loadChatHistory;
