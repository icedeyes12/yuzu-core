// Clean route URLs served by the backend in SPA mode (/chat/{id}, /config,
// /about, ...). The Vite dev server maps these to the MPA entries via the
// fallback middleware in vite.config.js; the backend serves the built dist at
// the same paths, so one URL scheme works in dev, local single-origin, and the
/**
 * Builds the chat page URL, optionally targeting a session.
 * @param {string} [sessionId] - The session identifier to include in the URL.
 * @return {string} The chat page URL.
 */
export function chatUrl(sessionId) {
	return sessionId
		? `/chat.html?session=${encodeURIComponent(sessionId)}`
		: "/chat.html";
}

/**
 * Creates the URL for the home page.
 * @returns {string} The home page URL.
 */
export function homeUrl() {
	return "/index.html";
}

/**
 * Build the configuration page URL.
 * @return {string} The configuration page URL.
 */
export function configUrl() {
	return "/config.html";
}

/**
 * Build the URL for the about page.
 * @return {string} The about page URL.
 */
export function aboutUrl() {
	return "/about.html";
}

/**
 * Build the login page URL.
 * @return {string} The login page URL.
 */
export function loginUrl() {
	return "/login.html";
}
