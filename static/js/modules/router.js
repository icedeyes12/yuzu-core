// FILE: static/js/modules/router.js
// DESCRIPTION: URL-based session routing for shareable URLs

/**
 * Handles URL-based session routing for shareable URLs.
 * Enables /chat?session=123 style navigation without page reloads.
 */
export class RouterManager {
	constructor() {
		this.currentSessionId = null;
		this.isInitialized = false;
	}

	/**
	 * Initialize router from current URL on page load.
	 * @returns {number|null} Session ID from URL or null
	 */
	initFromURL() {
		const params = new URLSearchParams(window.location.search);
		const sessionId = params.get("session");

		if (sessionId) {
			this.currentSessionId = parseInt(sessionId, 10);
			console.log(
				`[Router] Initialized with session ${this.currentSessionId} from URL`,
			);
		}

		this.isInitialized = true;
		this.setupPopStateHandler();
		return this.currentSessionId;
	}

	/**
	 * Update URL to reflect current session without page reload.
	 * @param {number} sessionId - Session ID to set in URL
	 */
	updateURL(sessionId) {
		if (!sessionId || sessionId === this.currentSessionId) return;

		this.currentSessionId = sessionId;
		const url = new URL(window.location.href);
		url.searchParams.set("session", sessionId.toString());

		window.history.pushState({ sessionId }, "", url);
		console.log(`[Router] URL updated to session ${sessionId}`);
	}

	/**
	 * Clear session parameter from URL.
	 */
	clearURL() {
		const url = new URL(window.location.href);
		url.searchParams.delete("session");
		window.history.pushState({}, "", url);
		this.currentSessionId = null;
	}

	/**
	 * Setup browser back/forward navigation handler.
	 */
	setupPopStateHandler() {
		window.addEventListener("popstate", (_event) => {
			const params = new URLSearchParams(window.location.search);
			const sessionId = params.get("session");

			if (sessionId && parseInt(sessionId, 10) !== this.currentSessionId) {
				console.log(`[Router] PopState: switching to session ${sessionId}`);
				this.currentSessionId = parseInt(sessionId, 10);
				// Trigger session switch without pushState
				if (typeof window.handleSessionSwitch === "function") {
					window.handleSessionSwitch(this.currentSessionId, false);
				}
			}
		});
	}
}

// Create singleton instance
export const router = new RouterManager();
