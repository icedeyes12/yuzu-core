// FILE: static/js/modules/scroll.js
// DESCRIPTION: Scroll-to-bottom button functionality

let scrollFrame = null;
let pendingScroll = null;
let followBottom = true;
let autoScrollUntil = 0;

function isAutoScrollActive() {
	return Date.now() < autoScrollUntil;
}

function setFollowBottom(chatContainer) {
	if (!isAutoScrollActive()) {
		followBottom = isNearBottom(chatContainer);
	}
}

export function createScrollButton() {
	const scrollBtn = document.getElementById("scrollToBottomBtn");
	if (!scrollBtn) return;

	scrollBtn.onclick = () => scrollToBottom({ force: true });
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

	chatContainer.addEventListener("scroll", () => {
		setFollowBottom(chatContainer);
		handleScroll();
	});
	window.addEventListener("resize", updateScrollButton);
	updateScrollButton();
}

/**
 * Scroll chat container to bottom smoothly.
 */
export function scrollToBottom({ force = false, follow = followBottom } = {}) {
	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer || (!force && !follow)) return;

	if (force) followBottom = true;
	autoScrollUntil = Date.now() + 250;
	pendingScroll = { force, follow: true };
	if (scrollFrame !== null) return;

	const scheduleFrame =
		typeof requestAnimationFrame === "function"
			? requestAnimationFrame
			: (callback) => setTimeout(callback, 16);
	scrollFrame = scheduleFrame(() => {
		scrollFrame = null;
		const request = pendingScroll;
		pendingScroll = null;
		if (!request || (!request.force && !request.follow)) return;

		chatContainer.scrollTo({
			top: chatContainer.scrollHeight,
			behavior: "smooth",
		});
	});

	const scrollBtn = document.getElementById("scrollToBottomBtn");
	if (scrollBtn) {
		scrollBtn.classList.add("hidden");
	}
}

export function isNearBottom(chatContainer, threshold = 160) {
	if (!chatContainer) return false;
	return (
		chatContainer.scrollHeight -
			(chatContainer.scrollTop + chatContainer.clientHeight) <=
		threshold
	);
}

export function shouldFollowBottom(chatContainer) {
	return followBottom || isNearBottom(chatContainer);
}
