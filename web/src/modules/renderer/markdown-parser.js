import { buildFenceHTML } from "../fence-registry.js";
import { renderMessageContent } from "../messages.js";
import { escapeHtml } from "../tool-renderer/dom-utils.js";
import { renderToolResultEvent } from "../tool-renderer/index.js";

export function installMarkedFenceRenderer() {
	if (!window.marked || window._fenceRendererInstalled) return;
	window._fenceRendererInstalled = true;
	const renderer = new window.marked.Renderer();
	renderer.code = (tokenOrCode, infostring) => {
		let source;
		let lang;
		if (
			tokenOrCode &&
			typeof tokenOrCode === "object" &&
			"text" in tokenOrCode
		) {
			source = tokenOrCode.text ?? "";
			lang = tokenOrCode.lang ?? "";
		} else {
			source = String(tokenOrCode ?? "");
			lang = infostring ?? "";
		}
		return buildFenceHTML(lang, source, true);
	};
	window.marked.setOptions({
		breaks: true,
		gfm: true,
		sanitize: false,
		renderer,
	});
	window._markedConfigured = true;
}

export function renderMessageHTML(msg) {
	installMarkedFenceRenderer();
	if (msg.role !== "tool")
		return classifyBufferedFences(
			renderMessageContent(msg.content, msg.role === "user"),
			msg.content,
		);
	try {
		const toolEvent = JSON.parse(msg.content);
		return renderToolResultEvent({
			...toolEvent,
			name: msg.toolResponse?.name || toolEvent.name,
			call_id: msg.toolResponse?.callId || toolEvent.call_id,
		});
	} catch (_error) {
		return renderToolResultEvent({
			name: msg.toolResponse?.name || "unknown",
			ok: false,
			data: { raw: msg.content },
		});
	}
}

function classifyBufferedFences(html, rawContent) {
	const bufferedLanguages = ["mermaid", "html"];
	let result = html;
	const raw = rawContent || "";
	for (const lang of bufferedLanguages) {
		if (!result.includes(`data-fence-lang="${lang}"`)) continue;
		const openRe = new RegExp(`^\`\`\`${lang}\\b`, "im");
		const openMatch = openRe.exec(raw);
		if (!openMatch) continue;
		const afterOpen = raw.slice(openMatch.index + openMatch[0].length);
		const closeCount = afterOpen
			.split("\n")
			.filter((line) => line.trim() === "```").length;
		if (closeCount === 0)
			result = replaceOuterDiv(
				result,
				`data-fence-lang="${lang}"`,
				`<div class="fence-block fence-block--pending" data-fence-lang="${lang}" data-fence-source="${escapeHtml(afterOpen)}" data-fence-strategy="buffered"></div>`,
			);
	}
	return result;
}

function replaceOuterDiv(html, marker, replacement) {
	const markerPos = html.indexOf(marker);
	if (markerPos === -1) return html;
	const divStart = html.lastIndexOf("<div", markerPos);
	if (divStart === -1) return html;
	let depth = 0;
	let cursor = divStart;
	while (cursor < html.length) {
		const nextOpen = html.indexOf("<div", cursor);
		const nextClose = html.indexOf("</div>", cursor);
		if (nextClose === -1) return html;
		if (nextOpen !== -1 && nextOpen < nextClose) {
			depth += 1;
			cursor = nextOpen + 4;
		} else {
			depth -= 1;
			cursor = nextClose + 6;
			if (depth === 0)
				return html.slice(0, divStart) + replacement + html.slice(cursor);
		}
	}
	return html;
}
