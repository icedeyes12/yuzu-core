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

// Clean login paths: the login UI is inside the SPA itself, served at either
// the built /login.html entry or the server-rendered /login route.
const LOGIN_PATHS = [loginUrl(), "/login"];

export function getLoginUrl() {
	return loginUrl();
}

export function redirectToLogin() {
	if (!LOGIN_PATHS.includes(window.location.pathname)) {
		window.location.assign(loginUrl());
	}
}

export function apiUrl(path) {
	const cleanPath = path.startsWith("/") ? path : `/${path}`;
	return `${API_BASE}${cleanPath}`;
}

function resolveRequestUrl(input) {
	if (typeof input === "string") {
		return /^https?:\/\//.test(input) ? input : apiUrl(input);
	}
	if (input instanceof URL) return input.toString();
	if (input instanceof Request) return input.url;
	return String(input);
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
	const targetUrl = resolveRequestUrl(input);
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
