// FILE: static/js/modules/index.js
// DESCRIPTION: Module index - exports all module components

import "./store-renderer.js"; // Initialize renderer subscriber on load

// Stream manager
export { eventRouter } from "./event-router.js";
// History loading
export { loadChatHistory, setupScrollListener } from "./history.js";
// Input behavior
export { initializeInputBehavior } from "./input.js";
// Messages
export {
	copyFullMessage,
	createMessageElement,
	escapeMessageHtml,
	findMessageById,
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
	generateMessageId,
	isProcessingMessage,
	MESSAGES_PER_PAGE,
	setIsProcessingMessage,
} from "./state.js";
export { chatStore } from "./store.js";
// Typing indicator
// The DOMRenderer owns the sole typing indicator.
