import { apiFetch, apiUrl } from "../modules/apiFetch.js";
import { homeUrl } from "../modules/links.js";

async function init() {
	// Point the provider buttons at the OAuth login route (works cross-origin
	// when VITE_API_BASE is set).
	for (const link of document.querySelectorAll("[data-auth-provider]")) {
		const provider = link.dataset.authProvider;
		if (provider) {
			link.href = apiUrl(`/api/v1/auth/login?provider=${provider}`);
		}
	}

	// Already signed in? Skip the login page.
	const response = await apiFetch("/api/v1/auth/me", {
		headers: { Accept: "application/json" },
	});
	if (response.ok) {
		window.location.assign(homeUrl());
	}
}

init();
