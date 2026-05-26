// FILE: static/js/modules/skeleton.js
// DESCRIPTION: Skeleton loading UI components

/**
 * Show skeleton loading state in chat container.
 */
export function showChatSkeleton() {
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
export function hideChatSkeleton() {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return;

	const skeletons = chatContainer.querySelectorAll(".skeleton-message");
	for (const s of skeletons) {
		s.remove();
	}
}
