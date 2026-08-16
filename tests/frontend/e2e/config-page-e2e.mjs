#!/usr/bin/env node
// In-browser E2E for the config page (provider selection, BYOK key save,
// profile save) against a real backend in SPA mode.
//
// Setup: build the SPA (cd web && npm run build), then start the backend:
//   SERVE_WEB_UI=true SERVE_SPA=true COOKIE_SECURE=false \
//     .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 5000
// Then run:  node tests/frontend/e2e/config-page-e2e.mjs
//
// The test mints its own throwaway user (see seed_user.py), so no real user
// data is touched; the user is deleted on cleanup. A fake provider key is
// used for the BYOK save, and the model catalog is pre-seeded in the browser
// (exactly as a successful discovery would) so the selection flow is
// deterministic without depending on a live provider API.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const BASE_URL = (process.env.E2E_BASE_URL || "http://127.0.0.1:5000").replace(
	/\/+$/,
	"",
);
// Prefer the project venv locally; fall back to the system python in CI.
const LOCAL_VENV = fileURLToPath(
	new URL("../../../.venv/bin/python", import.meta.url),
);
const PYTHON =
	process.env.E2E_PYTHON || (existsSync(LOCAL_VENV) ? LOCAL_VENV : "python3");
const SEED_SCRIPT = fileURLToPath(new URL("./seed_user.py", import.meta.url));

const PROVIDER = "chutes";
const TEST_KEY = "sk-test-e2e-abcdef";
const TEST_MODEL = "deepseek/deepseek-v4-flash";

function seedCreate() {
	const out = execFileSync(PYTHON, [SEED_SCRIPT, "create"], {
		encoding: "utf8",
	}).trim();
	return JSON.parse(out.split("\n").pop());
}

function seedDelete(userId) {
	execFileSync(PYTHON, [SEED_SCRIPT, "delete", userId], {
		encoding: "utf8",
	});
}

const { user_id: userId, token } = seedCreate();
let browser;

async function getConfig(context) {
	const response = await context.request.get(`${BASE_URL}/api/v1/config`, {
		headers: { Accept: "application/json" },
	});
	assert.equal(response.status(), 200, "GET /api/v1/config should be 200");
	return response.json();
}

try {
	browser = await chromium.launch();
	const context = await browser.newContext();

	// Authenticate as the throwaway user via the app's real session cookie.
	await context.addCookies([
		{ name: "yuzu_session", value: token, url: BASE_URL },
	]);

	// Pre-seed the user-scoped model catalog so the provider dropdown has
	// options (this is exactly what the app writes after a discovery).
	await context.addInitScript(
		({ storagePrefix, provider, model }) => {
			localStorage.setItem(
				`${storagePrefix}_provider_models`,
				JSON.stringify({
					[provider]: {
						models: [model, "qwen/qwen3-32b"],
						fetchedAt: Date.now(),
					},
				}),
			);
		},
		{ storagePrefix: `user_${userId}`, provider: PROVIDER, model: TEST_MODEL },
	);

	const page = await context.newPage();

	// ── Page load ─────────────────────────────────────────────────────────
	await page.goto(`${BASE_URL}/config`, { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#providers-grid .provider-card", {
		timeout: 20_000,
	});
	assert.match(
		await page.textContent("#current-provider"),
		/Not set|openrouter/,
		"current-provider header should render",
	);

	// ── Provider selection ────────────────────────────────────────────────
	// The chutes card is collapsed by default; expand it.
	const chutesCard = page.locator(
		`.provider-card:has(.set-active-btn[data-provider="${PROVIDER}"])`,
	);
	await chutesCard.locator(".provider-header").click();
	const modelSelect = page.locator(`#model-${PROVIDER}`);
	await modelSelect.waitFor({ state: "visible" });
	await modelSelect.selectOption(TEST_MODEL);
	await chutesCard
		.locator(`.set-active-btn[data-provider="${PROVIDER}"]`)
		.click();
	await page.waitForFunction(
		(provider) =>
			document
				.getElementById("current-provider")
				?.textContent.includes(`${provider}/`),
		PROVIDER,
		{ timeout: 15_000 },
	);
	assert.match(
		await page.textContent("#current-provider"),
		new RegExp(`${PROVIDER}/${TEST_MODEL.replaceAll("/", "\\/")}`),
		"current-provider should show chutes/<model>",
	);
	const cfgAfterSelect = await getConfig(context);
	assert.equal(
		cfgAfterSelect.current_provider,
		PROVIDER,
		"API should persist the selected provider",
	);
	assert.equal(
		cfgAfterSelect.current_model,
		TEST_MODEL,
		"API should persist the selected model",
	);

	// ── BYOK key save ─────────────────────────────────────────────────────
	const keyInput = page.locator(`#key-${PROVIDER}`);
	await keyInput.fill(TEST_KEY);
	await chutesCard
		.locator(`.save-byok-btn[data-provider="${PROVIDER}"]`)
		.click();
	await page
		.locator(".config-notification.success")
		.filter({ hasText: "key saved in browser" })
		.waitFor({ timeout: 10_000 });

	// Input should now show the masked value, not the raw key.
	const shownKey = await keyInput.inputValue();
	assert.notEqual(shownKey, TEST_KEY, "raw key must not remain visible");
	assert.match(
		shownKey,
		/^sk-test-/,
		"key input should show the masked prefix",
	);
	assert.ok(
		shownKey.endsWith(TEST_KEY.slice(-4)),
		"key input should end with the last 4 chars",
	);

	// Persisted to the user-scoped BYOK storage in localStorage.
	const storedByok = await page.evaluate((storagePrefix) => {
		const raw = localStorage.getItem(`${storagePrefix}_api_keys`);
		return raw ? JSON.parse(raw) : null;
	}, `user_${userId}`);
	assert.equal(
		storedByok?.providers?.[PROVIDER]?.api_key,
		TEST_KEY,
		"BYOK key should be saved in localStorage",
	);

	// ── Profile save ──────────────────────────────────────────────────────
	const displayName = "E2E Tester";
	const partnerName = "E2E Partner";
	await page.fill("#display-name", displayName);
	await page.fill("#partner-name", partnerName);
	await page.click("#save-profile");
	await page
		.locator(".config-notification.success")
		.filter({ hasText: "Profile settings saved" })
		.waitFor({ timeout: 10_000 });

	const cfgAfterProfile = await getConfig(context);
	assert.equal(
		cfgAfterProfile.profile.user_name,
		displayName,
		"API should persist the display name",
	);
	assert.equal(
		cfgAfterProfile.profile.partner_name,
		partnerName,
		"API should persist the partner name",
	);

	console.log(
		"config page E2E passed: provider selection, BYOK save, profile save",
	);
} finally {
	if (browser) await browser.close();
	seedDelete(userId);
}
