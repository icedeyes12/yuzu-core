import { mountSidebar } from "./components/sidebar.js";
import { bootstrapAuth } from "./modules/authBootstrap.js";
import { applySavedTheme } from "./modules/theme.js";

/**
 * Initializes the shared page shell, applies the saved theme, and bootstraps authentication.
 * @param {{ page?: string }} [options] - Optional page identifier applied to the document body.
 * @returns {Promise<object|null>} The authenticated user payload, or `null` if authentication fails.
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
		// Show error for service/network failures; bootstrapAuth already
		// handles 401/403 with redirectToLogin when redirectOnUnauthorized=true
		alert(`Failed to load session: ${error.message}`);
		return null;
	}
}
