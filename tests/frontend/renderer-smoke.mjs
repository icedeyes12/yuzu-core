import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const root = new URL("../../", import.meta.url);
const files = [
	"static/js/modules/store-renderer.js",
	"static/js/modules/renderer/dom-patcher.js",
	"static/js/modules/renderer/fence-lifecycle.js",
	"static/js/modules/renderer/markdown-parser.js",
	"static/js/modules/renderer/scroll-manager.js",
	"static/js/modules/scroll.js",
	"static/js/modules/fence-registry.js",
	"static/js/modules/fence-components.js",
];

const source = Object.fromEntries(
	await Promise.all(
		files.map(async (file) => [file, await readFile(new URL(file, root), "utf8")]),
	),
);

assert.match(source["static/js/modules/renderer/dom-patcher.js"], /patchContentContainer/);
assert.doesNotMatch(source["static/js/modules/store-renderer.js"], /contentContainer\.innerHTML/);
assert.match(source["static/js/modules/fence-registry.js"], /el\.dataset\.fenceActivated = "1"/);
assert.match(source["static/js/modules/fence-registry.js"], /for \(const el of elements\)/);
assert.match(source["static/js/modules/fence-components.js"], /fence-html-loading/);
assert.match(source["static/js/modules/fence-components.js"], /loadingEl\?\.remove\(\)/);
assert.match(source["static/js/modules/fence-components.js"], /fence-inspect-btn/);
assert.match(source["static/js/modules/fence-components.js"], /fence-html-source/);
assert.match(source["static/js/modules/fence-components.js"], /fence-html-iframe/);
assert.match(source["static/js/modules/renderer/scroll-manager.js"], /shouldFollowBottom/);
assert.match(source["static/js/modules/store-renderer.js"], /requestAnimationFrame/);
assert.match(source["static/js/modules/fence-registry.js"], /getFenceMetrics/);
assert.match(source["static/js/modules/fence-components.js"], /getMermaidMetrics/);

console.log(`renderer smoke contract passed (${files.length} modules)`);
