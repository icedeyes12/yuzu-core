import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../../", import.meta.url);
const files = [
	"static/js/modules/tool-renderer/schemas.js",
	"static/js/modules/tool-renderer/cards/terminal.js",
	"static/js/modules/tool-renderer/cards/image.js",
	"static/js/modules/tool-renderer/capabilities.js",
	"static/js/modules/tool-renderer/index.js",
	"static/js/modules/messages.js",
	"static/js/modules/tool-renderer/cards/weather.js",
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
		files.map(async (file) => [
			file,
			await readFile(new URL(file, root), "utf8"),
		]),
	),
);

assert.match(
	source["static/js/modules/renderer/dom-patcher.js"],
	/patchContentContainer/,
);
assert.doesNotMatch(
	source["static/js/modules/store-renderer.js"],
	/contentContainer\.innerHTML/,
);
assert.match(
	source["static/js/modules/fence-registry.js"],
	/el\.dataset\.fenceActivated = "1"/,
);
assert.match(
	source["static/js/modules/fence-registry.js"],
	/for \(const el of elements\)/,
);
assert.match(
	source["static/js/modules/fence-components.js"],
	/fence-html-loading/,
);
assert.match(
	source["static/js/modules/fence-components.js"],
	/loadingEl\?\.remove\(\)/,
);
assert.match(
	source["static/js/modules/fence-components.js"],
	/fence-inspect-btn/,
);
assert.match(
	source["static/js/modules/fence-components.js"],
	/fence-html-source/,
);
assert.match(
	source["static/js/modules/fence-components.js"],
	/fence-html-iframe/,
);
assert.match(
	source["static/js/modules/renderer/scroll-manager.js"],
	/shouldFollowBottom/,
);
assert.match(
	source["static/js/modules/store-renderer.js"],
	/requestAnimationFrame/,
);
assert.match(source["static/js/modules/fence-registry.js"], /getFenceMetrics/);
assert.match(
	source["static/js/modules/tool-renderer/cards/terminal.js"],
	/tool-card__output-toolbar/,
);
assert.match(
	source["static/js/modules/tool-renderer/cards/terminal.js"],
	/data-action="copy-tool-output"/,
);
assert.match(
	source["static/js/modules/tool-renderer/cards/terminal.js"],
	/tool-card__meta-group/,
);
assert.doesNotMatch(
	source["static/js/modules/tool-renderer/cards/terminal.js"],
	/JSON\.stringify/,
);
assert.match(source["static/js/modules/messages.js"], /\.tool-card__pre code/);
assert.match(
	source["static/js/modules/fence-components.js"],
	/getMermaidMetrics/,
);
assert.match(
	source["static/js/modules/messages.js"],
	/data-action="copy-tool-output"|copy-tool-prompt/,
);
assert.match(
	source["static/js/modules/tool-renderer/cards/image.js"],
	/image-card__prompt-code/,
);
assert.match(
	source["static/js/modules/tool-renderer/cards/image.js"],
	/data-action="copy-tool-prompt"/,
);
assert.match(
	source["static/js/modules/tool-renderer/capabilities.js"],
	/canCopy/,
);
assert.match(
	source["static/js/modules/tool-renderer/index.js"],
	/data-can-copy=/,
);

console.log(`renderer smoke contract passed (${files.length} modules)`);
