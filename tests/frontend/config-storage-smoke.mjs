import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../../", import.meta.url);

// Both the legacy Jinja UI and the Vite SPA must uphold the BYOK masking
// contract; verify the same invariants against each implementation.
const storageSources = [
	await readFile(new URL("static/js/client-storage.js", root), "utf8"),
	await readFile(new URL("web/src/modules/clientStorage.js", root), "utf8"),
];
const configSources = [
	await readFile(new URL("static/js/config.js", root), "utf8"),
	await readFile(new URL("web/src/pages/config.js", root), "utf8"),
];

for (const storage of storageSources) {
	assert.match(storage, /export function maskApiKey\(value\)/);
	assert.match(storage, /return `\$\{value\.slice\(0, 8\)\}\.\.\.\$\{value\.slice\(-4\)\}`/);
}
for (const config of configSources) {
	assert.match(config, /type="text" id="key-\$\{provider\}"/);
	assert.match(config, /value="\$\{escapeHtml\(maskApiKey\(provKey\)\)\}"/);
	assert.match(config, /maskedProviderKeys\.set\(input, storedKey\)/);
	assert.doesNotMatch(config, /data-stored-key/);
	assert.doesNotMatch(config, /type="password" id="key-/);
	assert.match(config, /function renderCapabilitySummary\(info\)/);
	assert.match(config, /capabilities\.structured_output/);
	assert.match(config, /capabilities\.image_generation/);
	assert.match(config, /limits\.context_window/);
	assert.match(config, /active-model-capabilities/);
	// DELETE /global-knowledge/{id} returns 204 with an empty body; the client
	// must not surface a spurious "Request failed (204)" error on success.
	assert.match(config, /response\.status === 204/);
}

console.log("config storage masking contract passed (legacy + SPA)");
