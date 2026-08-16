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

export function apiUrl(path) {
	const cleanPath = path.startsWith("/") ? path : `/${path}`;
	return `${API_BASE}${cleanPath}`;
}

// Clean login route: /login.html is the SPA route, /login is the Jinja route
// served by the backend when SERVE_SPA is disabled.
export function redirectToLogin() {
	if (
		window.location.pathname !== loginUrl() &&
		window.location.pathname !== "/login"
	) {
		window.location.assign(loginUrl());
	}
}

function resolveTargetUrl(input) {
	if (input instanceof Request) return input.url;
	if (input instanceof URL) return input.toString();
	const path = String(input);
	return /^https?:\/\//.test(path) ? path : apiUrl(path);
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
	const targetUrl = resolveTargetUrl(input);
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
