import { mountSidebar } from "./components/sidebar.js";
import { bootstrapAuth } from "./modules/authBootstrap.js";
import { applySavedTheme } from "./modules/theme.js";

/**
 * Shared page boot: mount the shell (sidebar), apply the theme (un-namespaced
 * fallback first, user-scoped key after /me resolves), then bootstrap the
 * session via GET /api/v1/auth/me. Unauthenticated visitors are redirected to
 * the login page by the auth gate.
 * @param {{ page?: string }} [options]
 * @returns {Promise<object|null>} The /me payload, or null when unauthenticated.
 */
export async function bootApp({ page } = {}) {
	if (page) document.body.dataset.page = page;

	mountSidebar();
	applySavedTheme();

	try {
		const me = await bootstrapAuth({ redirectOnUnauthorized: true });
		// Re-apply once the user-scoped theme key is known (fixes first-paint
		// flash for non-default themes).
		if (me) applySavedTheme();
		return me;
	} catch (error) {
		console.error("[boot] Auth bootstrap failed:", error);
		redirectToLogin();
		return null;
	}
}
