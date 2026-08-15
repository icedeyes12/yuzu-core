// FILE: static/js/modules/router.js
// DESCRIPTION: URL-based session routing for shareable URLs

/**
 * Handles URL-based session routing for shareable URLs.
 * Enables /chat?session=<uuid> style navigation without page reloads.
 */
export class RouterManager {
	constructor() {
		this.currentSessionId = null;
		this.isInitialized = false;
	}

	/**
	 * Initialize router from current URL on page load.
	 * @returns {string|null} Session ID (UUID) from URL or null
	 */
	initFromURL() {
		const pathParts = window.location.pathname.split("/").filter((p) => p);
		if (pathParts.length >= 2 && pathParts[0] === "chat") {
			this.currentSessionId = pathParts[1];
			console.log(
				`[Router] Initialized with session ${this.currentSessionId} from URL`,
			);
		} else {
			const params = new URLSearchParams(window.location.search);
			const sessionId = params.get("session");
			if (sessionId) {
				this.currentSessionId = sessionId;
				console.log(
					`[Router] Fallback initialized with session ${this.currentSessionId} from query`,
				);
			}
		}

		this.isInitialized = true;
		this.setupPopStateHandler();
		return this.currentSessionId;
	}

	/**
	 * Update URL to reflect current session without page reload.
	 * @param {string} sessionId - Session ID (UUID) to set in URL
	 */
	updateUrl(sessionId) {
		if (!sessionId || sessionId === this.currentSessionId) return;
		this.currentSessionId = sessionId;
		const url = new URL(window.location.href);
		if (url.pathname.startsWith("/chat/")) {
			url.pathname = `/chat/${sessionId}`;
			url.searchParams.delete("session");
		} else {
			url.pathname = `/chat/${sessionId}`;
			url.searchParams.delete("session");
		}
		window.history.pushState({ sessionId }, "", url);
	}

	/**
	 * Clear session parameter from URL.
	 */
	clearURL() {
		const url = new URL(window.location.href);
		if (url.pathname.startsWith("/chat/")) {
			url.pathname = "/chat";
		}
		url.searchParams.delete("session");
		window.history.pushState({}, "", url);
		this.currentSessionId = null;
	}

	/**
	 * Setup browser back/forward navigation handler.
	 */
	setupPopStateHandler(handleSessionSwitch) {
		window.addEventListener("popstate", (_event) => {
			// Extract from path first
			const pathParts = window.location.pathname.split("/").filter((p) => p);
			let sessionId = null;

			if (pathParts.length >= 2 && pathParts[0] === "chat") {
				sessionId = pathParts[1];
			} else {
				// Fallback to query string
				const params = new URLSearchParams(window.location.search);
				const fallbackSessionId = params.get("session");
				if (fallbackSessionId) sessionId = fallbackSessionId;
			}

			if (sessionId !== this.currentSessionId) {
				this.currentSessionId = sessionId;
				if (typeof handleSessionSwitch === "function") {
					void handleSessionSwitch(sessionId, false);
				}
			}
		});
	}
}

// Create singleton instance
export const router = new RouterManager();
