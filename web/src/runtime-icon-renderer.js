/* Generic UI icon definitions. Icons are data; callers own DOM insertion. */
import { escapeHtml } from "./modules/tool-renderer/dom-utils.js";

function createRuntimeIconRenderer() {
	const iconDefinitions = Object.freeze({
		chat: '<path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm8 5H6v-2h8v2zm4-6H6V6h12v2z"/>',
		image:
			'<path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM5 19l3.5-4.5 2.5 3.01L14.5 11l4.5 6H5z"/>',
		generate:
			'<path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9-2 2-2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM5 19l3.5-4.5 2.5 3.01L14.5 11l4.5 6H5z"/><path d="M14.5 11l1.5-2 1.5 2 2-1-2-1.5 2-1.5-2-1-1.5 2-1.5-2-1 1.5L13 8l-1.5 2z" opacity="0.7"/>',
		download: '<path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>',
		refresh:
			'<path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>',
		close:
			'<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>',
		upload:
			'<path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/>',
		copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
		send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
		edit: '<path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>',
		trash:
			'<path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>',
		"weather-sunny":
			'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/',
		"weather-partly-cloudy":
			'<path d="M8 19h8a4 4 0 0 0 .65-7.95A6 6 0 0 0 5.1 12.5 3.5 3.5 0 0 0 8 19Z"/><path d="M6 4v2M2 8h2M3.17 5.17l1.42 1.42"/',
		"weather-cloudy":
			'<path d="M7 19h10a4 4 0 0 0 .65-7.95A6 6 0 0 0 5.1 12.5 3.5 3.5 0 0 0 7 19Z"/>',
		"weather-fog": '<path d="M4 10h16M2 14h20M5 18h14"/>',
		"weather-rain":
			'<path d="M7 15h10a4 4 0 0 0 .65-7.95A6 6 0 0 0 5.1 8.5 3.5 3.5 0 0 0 7 15Z"/><path d="M8 18v2M12 18v2M16 18v2"/>',
		"weather-storm":
			'<path d="M7 15h10a4 4 0 0 0 .65-7.95A6 6 0 0 0 5.1 8.5 3.5 3.5 0 0 0 7 15Z"/><path d="m13 15-2 4h3l-2 4"/>',
		"weather-snow":
			'<path d="M12 3v18M4.22 6.22l15.56 11.56M19.78 6.22 4.22 17.78M5 12h14"/>',
	});

	function get(name) {
		return iconDefinitions[name] || null;
	}

	function render(name, options = {}) {
		const path = get(name);
		if (!path) return "";
		const size = Number(options.size) || 20;
		const className = options.className
			? ` class="${escapeHtml(options.className)}"`
			: "";
		const stroke = options.stroke || "currentColor";
		const strokeWidth = options.strokeWidth || 0;
		const fill = options.fill || (strokeWidth ? "none" : "currentColor");
		const linecap = strokeWidth
			? ' stroke-linecap="round" stroke-linejoin="round"'
			: "";
		return `<svg${className} width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${linecap} aria-hidden="true" focusable="false">${path}</svg>`;
	}

	return Object.freeze({
		definitions: iconDefinitions,
		get,
		render,
	});
}

export const RuntimeIconRenderer = createRuntimeIconRenderer();
export const renderRuntimeIcon = RuntimeIconRenderer.render;
