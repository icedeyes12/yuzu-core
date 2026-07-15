// FILE: static/js/modules/tool-renderer/dom-utils.js
// DESCRIPTION: Tiny DOM helpers shared by the card renderers.

export function escapeHtml(value) {
	if (value === null || value === undefined) return "";
	const str = String(value);
	return str.replace(
		/[&<>"']/g,
		(c) =>
			({
				"&": "&amp;",
				"<": "&lt;",
				">": "&gt;",
				'"': "&quot;",
				"'": "&#39;",
			})[c],
	);
}

export function safeImagePath(value) {
	if (typeof value !== "string" || !value) return null;
	const cleaned = value.trim().replace(/\\/g, "/");
	if (
		cleaned.startsWith("/") ||
		cleaned.startsWith("../") ||
		cleaned.includes("/../") ||
		cleaned.includes("/./")
	) {
		return null;
	}
	if (cleaned.startsWith("static/")) {
		return `/${cleaned}`;
	}
	if (cleaned.startsWith("/static/")) {
		return cleaned;
	}
	return cleaned;
}

export function safeHttpUrl(value) {
	if (typeof value !== "string" || !value) return null;
	try {
		const u = new URL(value);
		if (u.protocol !== "https:" && u.protocol !== "http:") return null;
		return u.toString();
	} catch (_e) {
		return null;
	}
}
