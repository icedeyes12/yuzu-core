// FILE: static/js/modules/tool-renderer/cards/terminal.js
// DESCRIPTION: Terminal renderer for execution tools (bash, python, sql).
// Renders strictly from validated structured fields. Never parses text.

import { escapeHtml } from "../dom-utils.js";

function terminalHeaderLine(_language) {
	// No "bash"/"zsh" branding. Generic title is enough.
	return "Terminal";
}

function renderTerminalCard(normalised) {
	const { command, stdout, stderr, exit_code, duration_ms, language } =
		normalised;

	const headerLabel = terminalHeaderLine(language);

	const lines = [`$ ${command}`];
	if (stdout) lines.push(stdout);
	const stderrTrimmed = (stderr || "").trim();
	if (stderrTrimmed) {
		lines.push("[stderr]");
		lines.push(stderrTrimmed);
	}

	const body = escapeHtml(lines.join("\n"));

	const exitOk = exit_code === 0;
	const exitClass = exitOk ? "exec-exit-ok" : "exec-exit-fail";
	const durationLabel = `Duration: ${duration_ms ?? 0} ms`;

	return [
		`<details class="tool-card tool-card--exec" open>`,
		`<summary class="tool-card__header">`,
		`<span class="tool-card__icon" aria-hidden="true"><span class="visual-icon visual-icon--terminal">›_</span></span>`,
		`<span class="tool-card__title">${escapeHtml(headerLabel)}</span>`,
		`<span class="tool-card__meta ${exitClass}">Exit ${exit_code}</span>`,
		`</summary>`,
		`<div class="tool-card__body tool-card__body--terminal">`,
		`<pre class="tool-card__pre"><code>${body}</code></pre>`,
		`<div class="tool-card__footer">`,
		`<span class="tool-card__exit ${exitClass}">Exit Code: ${exit_code}</span>`,
		`<span class="tool-card__duration">${escapeHtml(durationLabel)}</span>`,
		`</div>`,
		`</div>`,
		`</details>`,
	].join("");
}

export { renderTerminalCard };
