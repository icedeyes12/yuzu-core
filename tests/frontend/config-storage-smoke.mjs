import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../../", import.meta.url);
const storage = await readFile(new URL("static/js/client-storage.js", root), "utf8");
const config = await readFile(new URL("static/js/config.js", root), "utf8");

assert.match(storage, /export function maskApiKey\(value\)/);
assert.match(storage, /return `\$\{value\.slice\(0, 8\)\}\.\.\.\$\{value\.slice\(-4\)\}`/);
assert.match(config, /type="text" id="key-\$\{provider\}"/);
assert.match(config, /value="\$\{escapeHtml\(maskApiKey\(provKey\)\)\}"/);
assert.match(config, /maskedProviderKeys\.set\(input, storedKey\)/);
assert.doesNotMatch(config, /data-stored-key/);
assert.doesNotMatch(config, /type="password" id="key-/);

console.log("config storage masking contract passed");
