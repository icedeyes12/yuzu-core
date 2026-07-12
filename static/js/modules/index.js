// FILE: static/js/modules/index.js
// DESCRIPTION: Module index - exports all module components

import "./store-renderer.js"; // Initialize renderer subscriber on load

// History loading
export { setupScrollListener, loadChatHistory } from "./history.js";
// Input behavior
export { initializeInputBehavior } from "./input.js";
// Messages
export {
	copyFullMessage,
	createMessageElement,
	escapeMessageHtml,
	formatTimestamp,
	getCurrentTime24h,
	isRenderableHistoryRole,
	renderMessageContent,
} from "./messages.js";
// Multimodal manager
export { MultimodalManager } from "./multimodal.js";
// Router
export { RouterManager, router } from "./router.js";

// Scroll functions
export {
	createScrollButton,
	initializeScrollButtonAutoHide,
	scrollToBottom,
} from "./scroll.js";
// Skeleton loading
export { hideChatSkeleton, showChatSkeleton } from "./skeleton.js";
// State management
export {
	currentAbortController,
	currentStreamMessage,
	findMessageById,
	generateMessageId,
	isProcessingMessage,
	MESSAGES_PER_PAGE,
	setCurrentAbortController,
	setCurrentStreamMessage,
	setIsProcessingMessage,
} from "./state.js";
// Stream manager
export {
	eventRouter
} from "./event-router.js";
export {
	chatStore
} from "./store.js";
// Typing indicator
export {
	hideTypingIndicator,
	showTypingIndicator,
} from "./typing-indicator.js";
