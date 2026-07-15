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
	if (typeof value !== "string" || !value.trim()) return null;
	const cleaned = value.trim().replace(/\\/g, "/");
	const match = cleaned.match(
		/^(?:\/?static\/)?(generated_images|uploads)\/([^/?#]+)$/,
	);
	if (!match) return null;
	const [, directory, filename] = match;
	if (
		filename === "." ||
		filename === ".." ||
		filename.includes("..") ||
		!/^[-A-Za-z0-9_.]+\.(?:png|jpe?g|webp|gif)$/i.test(filename)
	) {
		return null;
	}
	return `/api/static/${directory}/${encodeURIComponent(filename)}`;
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
