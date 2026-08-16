// Clean route URLs served by the backend in SPA mode (/chat/{id}, /config,
// /about, ...). The Vite dev server maps these to the MPA entries via the
// fallback middleware in vite.config.js; the backend serves the built dist at
// the same paths, so one URL scheme works in dev, local single-origin, and the
// Phase 4 static-host deployment.
export function chatUrl(sessionId) {
	return sessionId ? `/chat/${encodeURIComponent(sessionId)}` : "/chat";
}

export function homeUrl() {
	return "/";
}

export function configUrl() {
	return "/config";
}

export function aboutUrl() {
	return "/about";
}
