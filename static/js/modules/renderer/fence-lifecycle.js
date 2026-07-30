import {
	activateFenceBlocks,
	cancelFenceAsyncWork,
	cleanupFenceBlocks,
	flushPendingFenceBlocks,
} from "../fence-registry.js";

export function activateMessageFences(messageElement, message, isGenerating) {
	const contentContainer = messageElement?.querySelector(".message-content");
	if (!contentContainer) return;
	activateFenceBlocks(contentContainer);
	if (isGenerating || !message.metadata?.isFrozen) return;
	flushPendingFenceBlocks(contentContainer);
	activateFenceBlocks(contentContainer);
}

export function cancelMessageFenceWork() {
	const container = document.getElementById("chatContainer");
	if (!container) return;
	cancelFenceAsyncWork(container);
}

export function cleanupMessageFences(messageElement) {
	cancelFenceAsyncWork(messageElement);
	cleanupFenceBlocks(messageElement);
}
