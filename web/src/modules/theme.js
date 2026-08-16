import { getUserThemeStorageKey } from "./clientStorage.js";

export const DEFAULT_THEME = "stellar-night-suisei";

// The user-scoped theme key is authoritative once /me resolves; before that we
// fall back to the un-namespaced "theme" key or the document attribute so the
/**
 * Retrieves the saved theme for the current user or the available fallback theme.
 * @returns {string} The user-specific theme, generic saved theme, document theme, or default theme.
 */
export function getSavedTheme() {
	const userKey = getUserThemeStorageKey();
	if (userKey) {
		const saved = localStorage.getItem(userKey);
		if (saved) return saved;
	}
	return (
		localStorage.getItem("theme") ||
		document.documentElement.getAttribute("data-theme") ||
		DEFAULT_THEME
	);
}

/**
 * Applies a theme to the document root and body.
 * @param {string} theme - The theme identifier to apply.
 */
export function applyTheme(theme) {
	document.documentElement.setAttribute("data-theme", theme);
	document.body.setAttribute("data-theme", theme);
}

/**
 * Applies the user's saved theme to the document.
 */
export function applySavedTheme() {
	applyTheme(getSavedTheme());
}

/**
 * Saves a theme for general and, when available, user-specific use.
 * @param {string} theme - The theme to save.
 */
export function persistTheme(theme) {
	localStorage.setItem("theme", theme);
	const userKey = getUserThemeStorageKey();
	if (userKey) {
		localStorage.setItem(userKey, theme);
	}
}
