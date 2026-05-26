// FILE: static/js/modules/scroll.js
// DESCRIPTION: Scroll-to-bottom button functionality

/**
 * Create scroll button click handler.
 */
export function createScrollButton() {
	const scrollBtn = document.getElementById("scrollToBottomBtn");
	if (!scrollBtn) return;

	scrollBtn.onclick = scrollToBottom;
	initializeScrollButtonAutoHide();
}

/**
 * Initialize auto-hide behavior for scroll button.
 */
export function initializeScrollButtonAutoHide() {
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

/**
 * Scroll chat container to bottom smoothly.
 */
export function scrollToBottom() {
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
