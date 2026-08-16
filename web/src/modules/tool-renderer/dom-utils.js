// FILE: static/js/modules/tool-renderer/dom-utils.js
// DESCRIPTION: Shared DOM/text helpers — canonical escapeHtml lives here.

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
	if (/^[a-z][a-z\d+.-]*:/i.test(cleaned)) return null;

	const pathOnly = cleaned.split(/[?#]/, 1)[0];
	const match =
		pathOnly.match(/(?:^|\/)static\/(generated_images|uploads)\/([^/]+)$/i) ||
		pathOnly.match(/^\/?(generated_images|uploads)\/([^/]+)$/i);
	if (!match) return null;

	const directory = match[1];
	let filename;
	try {
		filename = decodeURIComponent(match[2]);
	} catch (_error) {
		return null;
	}
	if (
		filename === "." ||
		filename === ".." ||
		filename.includes("..") ||
		!/^[-A-Za-z0-9_.]+\.(?:png|jpe?g|webp|gif)$/i.test(filename)
	) {
		return null;
	}
	return `/api/v1/static/${directory}/${encodeURIComponent(filename)}`;
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
