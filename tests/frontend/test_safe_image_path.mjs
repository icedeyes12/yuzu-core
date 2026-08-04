import assert from "node:assert/strict";
import { safeImagePath } from "../../static/js/modules/tool-renderer/dom-utils.js";

const validPaths = [
	"/api/v1/static/generated_images/generated.png",
	"/api/v1/static/uploads/upload.webp",
	"generated_images/generated.png",
	"/static/uploads/upload.webp",
];

for (const value of validPaths) {
	assert.ok(safeImagePath(value), `expected valid image path: ${value}`);
}

for (const value of [
	"/etc/passwd",
	"https://example.com/image.png",
	"/api/v1/static/generated_images/../secret.png",
	"/api/v1/static/generated_images/not-an-image.txt",
	"/api/v1/static/generated_images/",
]) {
	assert.equal(
		safeImagePath(value),
		null,
		`expected unsafe image path: ${value}`,
	);
}

assert.equal(
	safeImagePath("/api/v1/static/generated_images/generated.png"),
	"/api/v1/static/generated_images/generated.png",
);
assert.equal(
	safeImagePath(
		"/storage/emulated/0/projects/yuzu-companion/static/uploads/upload.jpg",
	),
	"/api/v1/static/uploads/upload.jpg",
);
assert.equal(
	safeImagePath("/api/v1/static/uploads/upload-name.jpg"),
	"/api/v1/static/uploads/upload-name.jpg",
);
