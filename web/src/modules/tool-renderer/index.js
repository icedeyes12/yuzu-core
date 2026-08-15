import {
	imageToolCardCapability,
	noCopyToolCardCapability,
	terminalToolCardCapability,
} from "./capabilities.js";
import { renderGenericCard } from "./cards/generic.js";
import { renderImageCard } from "./cards/image.js";
import { renderTerminalCard } from "./cards/terminal.js";
import { renderWeatherCard } from "./cards/weather.js";
import { escapeHtml } from "./dom-utils.js";
import { canonicalToolName, parseToolResult } from "./schemas.js";

const TOOL_RENDERERS = {
	exec: {
		render: renderTerminalCard,
		capability: terminalToolCardCapability,
	},
	image: {
		render: renderImageCard,
		capability: imageToolCardCapability,
	},
	weather: {
		render: renderWeatherCard,
		capability: noCopyToolCardCapability,
	},
};

function renderToolResult({ name, data, call_id, ok, error }) {
	const parsed = parseToolResult({ name, data, ok, error }, name);
	const payload = parsed.normalised || {};
	const renderer = TOOL_RENDERERS[parsed.schema_kind];
	if (
		parsed.ok === false &&
		parsed.error &&
		payload.status !== "location_required"
	) {
		return {
			html: renderGenericCard(
				canonicalToolName(name),
				{ ok: false, error_message: parsed.error },
				{
					error_category: data.error_category || "tool_execution_error",
					error: parsed.error,
				},
			),
			capability: noCopyToolCardCapability,
		};
	}
	if (parsed.validationError) {
		return {
			html: renderGenericCard(
				canonicalToolName(name),
				{
					ok: false,
					error_message:
						parsed.error || "Tool payload did not match the expected schema.",
				},
				data,
			),
			capability: noCopyToolCardCapability,
		};
	}
	if (renderer) {
		const capability = renderer.capability;
		const copyableContent = capability.canCopy
			? capability.getCopyableContent(payload)
			: "";
		return {
			html: renderer.render(payload, call_id, { copyableContent }),
			capability,
		};
	}
	return {
		html: renderGenericCard(
			canonicalToolName(name),
			payload,
			payload.fields || payload,
		),
		capability: noCopyToolCardCapability,
	};
}

export function renderToolEvent(eventType, data) {
	if (eventType === "tool_call") {
		const name = data?.name || "unknown";
		const callId = data?.id || "";
		return `<details class="tool-call-indicator" data-call-id="${escapeHtml(callId)}"><summary><span class="visual-status visual-status--info"><span class="visual-status__mark" aria-hidden="true">i</span><span>Calling ${escapeHtml(name)}…</span></span></summary><pre>Waiting for result…</pre></details>`;
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
	const rendered = renderToolResult(payload);
	const statusIcon = payload.ok ? "✓" : "!";
	const statusClass = payload.ok
		? "visual-status--success"
		: "visual-status--danger";
	const canonicalName = canonicalToolName(payload.name);
	const status =
		canonicalName === "exec"
			? ""
			: `<div class="tool-result__status ${statusClass}"><span class="visual-status__mark" aria-hidden="true">${statusIcon}</span><span>${escapeHtml(payload.name)}</span></div>`;
	return `<div class="tool-result" data-tool-name="${escapeHtml(payload.name)}" data-can-copy="${rendered.capability.canCopy ? "true" : "false"}">${status}<div class="tool-result-content">${rendered.html}</div></div>`;
}

export function getToolCardCapability(schemaKind) {
	return TOOL_RENDERERS[schemaKind]?.capability || noCopyToolCardCapability;
}
