import { getUserThemeStorageKey } from "./clientStorage.js";

export const DEFAULT_THEME = "stellar-night-suisei";

// The user-scoped theme key is authoritative once /me resolves; before that we
// fall back to the un-namespaced "theme" key or the document attribute so the
// first paint is not a flash of the default theme.
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

export function applyTheme(theme) {
	document.documentElement.setAttribute("data-theme", theme);
	document.body.setAttribute("data-theme", theme);
}

export function applySavedTheme() {
	applyTheme(getSavedTheme());
}

export function persistTheme(theme) {
	localStorage.setItem("theme", theme);
	const userKey = getUserThemeStorageKey();
	if (userKey) {
		localStorage.setItem(userKey, theme);
	}
}
