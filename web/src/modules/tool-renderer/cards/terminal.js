// FILE: static/js/modules/tool-renderer/cards/terminal.js
// DESCRIPTION: Terminal renderer for execution tools (bash, python, sql).
// Renders strictly from validated structured fields. Never parses text.

import { renderRuntimeIcon } from "../../../runtime-icon-renderer.js";
import { escapeHtml } from "../dom-utils.js";

function renderTerminalCard(
	normalised,
	_callId,
	{ copyableContent = "" } = {},
) {
	const {
		command = "",
		stdout = "",
		stderr = "",
		exit_code = null,
		duration_ms = 0,
		status = "completed",
	} = normalised || {};
	const output = copyableContent || [stdout, stderr].filter(Boolean).join("\n");
	const hasOutput = Boolean(output);
	const success = status !== "error" && (exit_code === null || exit_code === 0);
	const statusLabel = success ? "Success" : "Failed";
	const statusClass = success ? "exec-exit-ok" : "exec-exit-fail";
	const copyIcon =
		renderRuntimeIcon("copy", {
			size: 14,
			strokeWidth: 2,
			className: "tool-card__copy-icon",
		}) || "";
	const commandMarkup = command
		? `<div class="tool-card__command-line"><span>$ </span>${escapeHtml(command)}</div>`
		: "";
	const outputMarkup = hasOutput
		? `<span class="tool-card__stream">${escapeHtml(stdout)}</span>${stderr ? `<span class="tool-card__stream tool-card__stream--stderr">${escapeHtml(stderr)}</span>` : ""}`
		: "";

	return [
		`<details class="tool-card tool-card--exec"${hasOutput ? " open" : ""}>`,
		`<summary class="tool-card__header">`,
		`<span class="tool-card__identity"><span class="tool-card__title">Terminal</span></span>`,
		`<span class="tool-card__toggle" aria-hidden="true">${hasOutput ? "Hide output" : "Show output"}</span>`,
		`<span class="tool-card__meta-group">`,
		`<span class="tool-card__meta ${statusClass}">${success ? "✓" : "!"} ${statusLabel}</span>`,
		`<span class="tool-card__meta">Exit ${escapeHtml(exit_code ?? "—")}</span>`,
		`<span class="tool-card__meta">${escapeHtml(formatDuration(duration_ms))}</span>`,
		`</span>`,
		`</summary>`,
		`<div class="tool-card__body">`,
		commandMarkup,
		`<div class="tool-card__output">`,
		`<div class="tool-card__output-toolbar">`,
		`<span class="tool-card__output-label">${hasOutput ? "Output" : "No output"}</span>`,
		`<button class="tool-card__copy" type="button" data-action="copy-tool-output"${hasOutput ? "" : " disabled"} aria-label="Copy terminal output" title="Copy terminal output">${copyIcon}<span>Copy</span></button>`,
		`</div>`,
		`<pre class="tool-card__pre"><code>${outputMarkup}</code></pre>`,
		`</div>`,
		`<div class="tool-card__footer">`,
		`<span class="tool-card__output-state">${hasOutput ? "Output ready" : "No output produced"}</span>`,
		`</div>`,
		`</div>`,
		`</details>`,
	].join("");
}

function formatDuration(durationMs) {
	const value = Number(durationMs);
	if (!Number.isFinite(value) || value < 0) return "—";
	return `${Math.round(value)}ms`;
}

export { renderTerminalCard };
