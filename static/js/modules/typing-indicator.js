// FILE: static/js/modules/typing-indicator.js
// DESCRIPTION: Dynamic typing indicator for streaming responses

let _typingIndicatorElement = null;
let _typingIndicatorShownAt = 0;
const TYPING_INDICATOR_MIN_DURATION_MS = 300;

/**
 * Show typing indicator as an in-flow message.
 * @returns {HTMLElement|null} The typing indicator element
 */
export function showTypingIndicator() {
	// Remove any existing indicator
	hideTypingIndicator(true);

	// Ensure layout is up-to-date before showing indicator
	if (typeof window.updateDynamicLayout === "function") {
		window.updateDynamicLayout();
	}

	const chatContainer = document.getElementById("chatContainer");
	if (!chatContainer) return null;

	const msg = document.createElement("div");
	msg.className = "message ai typing-indicator-message";
	msg.id = "typingIndicatorMessage";

	const dots = document.createElement("div");
	dots.className = "typing-dots";
	dots.innerHTML = "<span></span><span></span><span></span>";
	msg.appendChild(dots);

	chatContainer.appendChild(msg);
	_typingIndicatorElement = msg;
	_typingIndicatorShownAt = Date.now();

	// Import scrollToBottom dynamically to avoid circular dependency
	import("./scroll.js").then(({ scrollToBottom }) => {
		scrollToBottom();
	});

	return msg;
}

/**
 * Hide typing indicator with minimum visibility duration.
 * @param {boolean} force - Skip minimum duration check
 */
export function hideTypingIndicator(force = false) {
	if (!_typingIndicatorElement) return;

	const elapsed = Date.now() - _typingIndicatorShownAt;
	const remaining = TYPING_INDICATOR_MIN_DURATION_MS - elapsed;

	if (force || remaining <= 0) {
		_typingIndicatorElement.remove();
		_typingIndicatorElement = null;
	} else {
		// Ensure minimum visibility
		setTimeout(() => {
			if (_typingIndicatorElement) {
				_typingIndicatorElement.remove();
				_typingIndicatorElement = null;
			}
		}, remaining);
	}
}
