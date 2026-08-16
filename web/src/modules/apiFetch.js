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

export function apiUrl(path) {
	const cleanPath = path.startsWith("/") ? path : `/${path}`;
	return `${API_BASE}${cleanPath}`;
}

export function getLoginUrl() {
	return LOGIN_URL;
}

export function redirectToLogin() {
	if (
		window.location.pathname !== LOGIN_URL &&
		window.location.pathname !== "/login"
	) {
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
