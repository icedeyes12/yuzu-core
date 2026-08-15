import { apiFetch, redirectToLogin } from "./apiFetch.js";
import { setStorageNamespace } from "./clientStorage.js";

let cachedMe = null;

export function getCachedMe() {
	return cachedMe;
}

/**
 * Fetch /api/v1/auth/me, cache the identity, and derive the user-scoped
 * storage namespace (user_{user_id}) used for BYOK keys, theme, and caches.
 * @param {{ redirectOnUnauthorized?: boolean }} [options]
 * @returns {Promise<object|null>} The /me payload, or null when unauthenticated.
 */
export async function bootstrapAuth({ redirectOnUnauthorized = true } = {}) {
	if (cachedMe) return cachedMe;

	const response = await apiFetch("/api/v1/auth/me", {
		headers: { Accept: "application/json" },
	});

	if (response.status === 401 || response.status === 403) {
		if (redirectOnUnauthorized) redirectToLogin();
		return null;
	}

	if (!response.ok) {
		throw new Error(`Failed to load session: HTTP ${response.status}`);
	}

	cachedMe = await response.json();
	if (cachedMe?.user_id) {
		setStorageNamespace(cachedMe.user_id);
	}
	return cachedMe;
}

export function resetBootstrap() {
	cachedMe = null;
}
