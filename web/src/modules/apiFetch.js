import { encodeByokConfig } from "./clientStorage.js";

// Same-origin when the backend serves the built SPA; cross-origin when the
// SPA is deployed to a static host (set VITE_API_BASE at build time).
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

const LLM_ENDPOINTS = [
	"/api/v1/send_message",
	"/api/v1/send_message_stream",
	"/api/v1/generate_image",
];

// Clean login route: the login UI is inside the SPA itself (/login or /login.html)
const LOGIN_URL = "/login.html";

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
 * Gets the login page URL.
 * @return {string} The login page URL.
 */
export function getLoginUrl() {
	return LOGIN_URL;
}

/**
 * Redirects the current page to the login page when it is not already a login route.
 */
export function redirectToLogin() {
	if (
		window.location.pathname !== LOGIN_URL &&
		window.location.pathname !== "/login"
	) {
		window.location.assign(getLoginUrl());
	}
}

/**
 * Fetch a request with session credentials and optional BYOK configuration for LLM endpoints.
 * Redirects to the login page when an API v1 request receives an authentication failure.
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

	if (LLM_ENDPOINTS.some((endpoint) => targetUrl.includes(endpoint))) {
		try {
			const encoded = encodeByokConfig();
			if (encoded) {
				headers.set("X-BYOK-Config", encoded);
			}
		} catch {
			// BYOK settings are optional; continue without them.
		}
	}

	const response = await fetch(targetUrl, {
		...init,
		headers,
		credentials: "include",
	});

	if (
		(response.status === 401 || response.status === 403) &&
		targetUrl.includes("/api/v1/")
	) {
		redirectToLogin();
	}

	return response;
}
