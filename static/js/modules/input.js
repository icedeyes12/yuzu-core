// FILE: static/js/modules/input.js
// DESCRIPTION: Input behavior and dynamic layout management

/**
 * Initialize input behavior with auto-resize and dynamic layout.
 */
export function initializeInputBehavior() {
	const input = document.getElementById("messageInput");
	const scrollBtn = document.getElementById("scrollToBottomBtn");
	const chatContainer = document.getElementById("chatContainer");

	if (!input) return;

	// Function to update dynamic layout based on input area height
	function updateDynamicLayout() {
		const inputArea = input.closest(".input-area");
		if (!inputArea) return;

		const inputAreaHeight = inputArea.offsetHeight;

		// Update scroll button position (10px above input area)
		if (scrollBtn) {
			scrollBtn.style.bottom = `${inputAreaHeight + 10}px`;
		}

		// Update chat container padding-bottom dynamically
		// Header height ~48px, so top padding is ~4.8rem
		// Bottom padding should be: input area height + margin for last message visibility
		if (chatContainer) {
			const headerHeight = 48; // Approximate header height in px
			const bottomMargin = 60; // Extra margin for last message visibility (increased for safety)
			chatContainer.style.paddingTop = `${headerHeight + 8}px`;
			chatContainer.style.paddingBottom = `${inputAreaHeight + bottomMargin}px`;
		}
	}

	// Auto-resize textarea
	input.oninput = () => {
		input.style.height = "auto";
		input.style.height = `${Math.min(input.scrollHeight, 400)}px`;
		updateDynamicLayout();
	};

	// Initial layout update
	updateDynamicLayout();

	// Update on window resize
	window.addEventListener("resize", updateDynamicLayout);

	// Use ResizeObserver for reliable input area height detection
	const inputArea = input.closest(".input-area");
	if (inputArea && typeof ResizeObserver !== "undefined") {
		const resizeObserver = new ResizeObserver(() => {
			updateDynamicLayout();
		});
		resizeObserver.observe(inputArea);

		// Also observe the input itself for height changes
		resizeObserver.observe(input);
	}

	// Expose globally for post-history and post-message updates
	window.updateDynamicLayout = updateDynamicLayout;
}
