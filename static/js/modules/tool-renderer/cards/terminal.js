// FILE: static/js/modules/tool-renderer/cards/terminal.js
// DESCRIPTION: Terminal renderer for execution tools (bash, python, sql).
// Renders strictly from validated structured fields. Never parses text.

import { escapeHtml } from "../dom-utils.js";

function terminalHeaderLine(_language) {
	// No "bash"/"zsh" branding. Generic title is enough.
	return "Terminal";
}

function formatDuration(durationMs) {
	const milliseconds = Number(durationMs);
	if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "";
	if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
	return `${(milliseconds / 1000).toFixed(1)} s`;
}

function renderTerminalCard(normalised) {
	const { command, stdout, stderr, exit_code, duration_ms, language } =
		normalised;

	const headerLabel = terminalHeaderLine(language);

	const lines = [];
	if (stdout) lines.push(stdout);
	const stderrTrimmed = (stderr || "").trim();
	if (stderrTrimmed) {
		lines.push("[stderr]");
		lines.push(stderrTrimmed);
	}

	const body = escapeHtml(lines.join("\n"));

	const exitOk = exit_code === 0;
	const exitClass = exitOk ? "exec-exit-ok" : "exec-exit-fail";
	const durationLabel = formatDuration(duration_ms);
	const output = stdout || stderrTrimmed;
	const hasOutput = Boolean(output);

	return [
		`<details class="tool-card tool-card--exec">`,
		`<summary class="tool-card__header">`,
		`<span class="tool-card__icon" aria-hidden="true"><span class="visual-icon visual-icon--terminal">›_</span></span>`,
		`<span class="tool-card__title">${escapeHtml(headerLabel)}</span>`,
		`<span class="tool-card__meta ${exitClass}">${exitOk ? "✓ Success" : "✕ Failed"}</span>`,
		`<span class="tool-card__meta">Exit ${escapeHtml(exit_code)}</span>`,
		`<span class="tool-card__meta tool-card__duration">${escapeHtml(durationLabel)}</span>`,
		`<span class="tool-card__toggle" aria-hidden="true">Show output</span>`,
		`</summary>`,
		`<div class="tool-card__body tool-card__body--terminal">`,
		`<div class="tool-card__command-line"><span aria-hidden="true">$</span> ${escapeHtml(command)}</div>`,
		`<pre class="tool-card__pre"><code>${body}</code></pre>`,
		`<div class="tool-card__footer">`,
		`<span class="tool-card__output-state">${hasOutput ? "Output" : "No output"}</span>`,
		`</div>`,
		`</div>`,
		`</details>`,
	].join("");
}

export { renderTerminalCard };
