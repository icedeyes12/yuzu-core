import { encodeByokConfig } from "./clientStorage.js";
import { loginUrl } from "./links.js";

// Same-origin when the backend serves the built SPA; cross-origin when the
// SPA is deployed to a static host (set VITE_API_BASE at build time).
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

const LLM_ENDPOINTS = [
	"/api/v1/send_message",
	"/api/v1/send_message_stream",
	"/api/v1/generate_image",
];

/**
 * Builds an API URL from a path.
 * @param {string} path - The API path, with or without a leading slash.
 * @return {string} The URL formed by combining the API base with the normalized path.
 */
export function apiUrl(path) {
	const cleanPath = path.startsWith("/") ? path : `/${path}`;
	return `${API_BASE}${cleanPath}`;
}

/**
 * Redirects the current page to the login page when it is not already a login route.
 */
export function redirectToLogin() {
	if (
		window.location.pathname !== loginUrl() &&
		window.location.pathname !== "/login"
	) {
		window.location.assign(loginUrl());
	}
}

/**
 * Fetch a request with session credentials and optional BYOK configuration for LLM endpoints.
 * Redirects to the login page when an API v1 request receives a 401 or 403 response.
 * @param {string|URL|Request} input - The request URL or input.
 * @param {RequestInit} [init] - Request options.
 * @returns {Promise<Response>} The fetch response.
 */
export async function apiFetch(input, init = {}) {
	let targetUrl;
	if (typeof input === "string") {
		targetUrl =
			input.startsWith("http://") || input.startsWith("https://")
				? input
				: apiUrl(input);
	} else if (input instanceof URL) {
		targetUrl = input.toString();
	} else if (input instanceof Request) {
		targetUrl = input.url;
	} else {
		targetUrl = String(input);
	}

	const headers = new Headers(init.headers || {});

	// Restrict BYOK header injection to same-origin LLM endpoints
	try {
		const url = new URL(targetUrl, window.location.origin);
		const baseOrigin = API_BASE
			? new URL(API_BASE, window.location.origin).origin
			: window.location.origin;
		const isSameOrigin = url.origin === baseOrigin;
		const isLlmEndpoint = LLM_ENDPOINTS.some(
			(endpoint) => url.pathname === endpoint,
		);

		if (isSameOrigin && isLlmEndpoint) {
			const encoded = encodeByokConfig();
			if (encoded) {
				headers.set("X-BYOK-Config", encoded);
			}
		}
	} catch {
		// BYOK settings are optional; continue without them.
	}

	const response = await fetch(targetUrl, {
		...init,
		headers,
		credentials: "include",
	});

	if (response.status === 401 || response.status === 403) {
		try {
			const url = new URL(targetUrl, window.location.origin);
			const baseOrigin = API_BASE
				? new URL(API_BASE, window.location.origin).origin
				: window.location.origin;
			if (url.origin === baseOrigin && url.pathname.includes("/api/v1/")) {
				redirectToLogin();
			}
		} catch {
			if (targetUrl.includes("/api/v1/")) {
				redirectToLogin();
			}
		}
	}

	return response;
}
