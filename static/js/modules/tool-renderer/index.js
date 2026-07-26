import { renderGenericCard } from "./cards/generic.js";
import { renderImageCard } from "./cards/image.js";
import { renderTerminalCard } from "./cards/terminal.js";
import { renderWeatherCard } from "./cards/weather.js";
import { canonicalToolName, parseToolResult } from "./schemas.js";

const TOOL_RENDERERS = {
	exec: renderTerminalCard,
	image: renderImageCard,
	weather: renderWeatherCard,
};

function renderToolResult({ name, data, call_id }) {
	const parsed = parseToolResult({ name, data }, name);
	const payload = parsed.normalised || {};
	if (parsed.validationError) {
		return renderGenericCard(
			canonicalToolName(name),
			{
				ok: false,
				error_message:
					parsed.error || "Tool payload did not match the expected schema.",
			},
			data,
		);
	}
	const renderer = TOOL_RENDERERS[parsed.schema_kind];
	if (renderer) return renderer(payload, call_id);
	return renderGenericCard(
		canonicalToolName(name),
		payload,
		payload.fields || payload,
	);
}

export function renderToolEvent(eventType, data) {
	if (eventType === "tool_call") {
		const name = data?.name || "unknown";
		const callId = data?.id || "";
		return `<details class="tool-call-indicator" data-call-id="${escapeAttr(callId)}"><summary><span class="visual-status visual-status--info"><span class="visual-status__mark" aria-hidden="true">i</span><span>Calling ${escapeHtml(name)}…</span></span></summary><pre>Waiting for result…</pre></details>`;
	}
	return eventType === "tool_result" ? renderToolResultEvent(data) : "";
}

export function renderToolResultEvent(data) {
	if (!data) return "";
	const payload = {
		ok: data.ok !== false,
		name: data.name || "unknown",
		call_id: data.call_id || "",
		data: data.data || {},
		error: data.error || "",
	};
	const card = renderToolResult(payload);
	const statusIcon = payload.ok ? "✓" : "!";
	const statusClass = payload.ok
		? "visual-status--success"
		: "visual-status--danger";
	return `<details class="tool-result" data-tool-name="${escapeAttr(payload.name)}" open><summary><span class="visual-status ${statusClass}"><span class="visual-status__mark" aria-hidden="true">${statusIcon}</span><span>${escapeHtml(payload.name)}</span></span></summary><div class="tool-result-content">${card}</div></details>`;
}

function escapeHtml(value) {
	return String(value ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

function escapeAttr(value) {
	return escapeHtml(value);
}
