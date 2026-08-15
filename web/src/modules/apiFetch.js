import { encodeByokConfig } from "./clientStorage.js";

// Same-origin when the backend serves the built SPA; cross-origin when the
// SPA is deployed to a static host (set VITE_API_BASE at build time).
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

const LLM_ENDPOINTS = [
	"/api/v1/send_message",
	"/api/v1/send_message_stream",
	"/api/v1/generate_image",
];

// Clean login route: the backend SPA mode serves /login, the Vite dev server
// maps it to login.html via the fallback, and a static host rewrites it.
const LOGIN_URL = "/login";

export function apiUrl(path) {
	return `${API_BASE}${path}`;
}

export function getLoginUrl() {
	return `${API_BASE}${LOGIN_URL}`;
}

export function redirectToLogin() {
	if (window.location.pathname !== LOGIN_URL) {
		window.location.assign(getLoginUrl());
	}
}

/**
 * Fetch wrapper for the API: credentials are always included (session cookie),
 * the BYOK config header is injected on LLM endpoints, and a 401/403 on an
 * /api/v1 request redirects to the login page (the auth gate).
 * @param {string|URL|Request} input
 * @param {RequestInit} [init]
 * @returns {Promise<Response>}
 */
export async function apiFetch(input, init = {}) {
	const url = typeof input === "string" ? input : input.url;
	const headers = new Headers(init.headers || {});

	if (LLM_ENDPOINTS.some((endpoint) => url.includes(endpoint))) {
		try {
			const encoded = encodeByokConfig();
			if (encoded) {
				headers.set("X-BYOK-Config", encoded);
			}
		} catch {
			// BYOK settings are optional; continue without them.
		}
	}

	const response = await fetch(url, {
		...init,
		headers,
		credentials: "include",
	});

	if (
		(response.status === 401 || response.status === 403) &&
		url.includes("/api/v1/")
	) {
		redirectToLogin();
	}

	return response;
}
