// FILE: static/js/modules/tool-renderer/capabilities.js
// DESCRIPTION: Shared capability contract for contextual tool-card actions.

export function createToolCardCapability({
	canCopy = false,
	getCopyableContent,
} = {}) {
	return Object.freeze({
		canCopy: Boolean(canCopy),
		getCopyableContent:
			typeof getCopyableContent === "function" ? getCopyableContent : () => "",
	});
}

export const terminalToolCardCapability = createToolCardCapability({
	canCopy: true,
	getCopyableContent: ({ stdout = "", stderr = "" } = {}) =>
		[stdout, stderr].filter(Boolean).join("\n"),
});

export const imageToolCardCapability = createToolCardCapability({
	canCopy: true,
	getCopyableContent: ({ prompt = "" } = {}) => String(prompt).trim(),
});

export const noCopyToolCardCapability = createToolCardCapability();
