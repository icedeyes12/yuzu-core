/**
 * DOM Utility Functions
 *
 * Universal helpers for DOM state preservation across renders
 */

/**
 * [ACCORDION PRESERVATION] Captures open state of all <details> elements in DOM order
 * @param {HTMLElement} container - DOM container to scan
 * @returns {boolean[]} Array of open states in document order
 */
export function captureDetailsState(container) {
	if (!container) return [];

	const detailsElements = container.querySelectorAll("details");
	return Array.from(detailsElements).map((d) => d.open);
}

/**
 * [ACCORDION PRESERVATION] Restores open state of <details> elements from captured state
 * @param {HTMLElement} container - DOM container to restore
 * @param {boolean[]} states - Array of open states from captureDetailsState
 */
export function restoreDetailsState(container, states) {
	if (!container || !states || states.length === 0) return;

	const detailsElements = container.querySelectorAll("details");

	// [RESILIENCE] Apply states with bounds checking
	// - If new DOM has fewer elements: only restore what exists (truncate)
	// - If new DOM has more elements: restore captured states, leave new ones default
	const minLen = Math.min(detailsElements.length, states.length);

	for (let i = 0; i < minLen; i++) {
		if (states[i]) {
			detailsElements[i].open = true;
		}
	}
}
