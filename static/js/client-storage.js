const userId = document.querySelector('meta[name="user-id"]')?.content || "";
const storageNamespace = userId ? `user_${userId}` : "";

export const BYOK_STORAGE_KEY = storageNamespace
	? `${storageNamespace}_api_keys`
	: "";
export const USER_THEME_STORAGE_KEY = storageNamespace
	? `${storageNamespace}_theme`
	: "";
export const DEFAULT_YUZU_PORTAL_BASE_URL = "http://localhost:20128/v1";

export function getUserStorageKey(suffix) {
	return storageNamespace ? `${storageNamespace}_${suffix}` : "";
}

export function getByokConfig() {
	if (!BYOK_STORAGE_KEY) return { providers: {} };
	try {
		const raw = localStorage.getItem(BYOK_STORAGE_KEY);
		const parsed = raw ? JSON.parse(raw) : {};
		if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
			return { providers: {} };
		}
		const providers =
			parsed.providers && typeof parsed.providers === "object"
				? parsed.providers
				: parsed;
		return { providers: { ...providers } };
	} catch {
		return { providers: {} };
	}
}

export function getByokProvider(provider) {
	const config = getByokConfig();
	const providerConfig = config.providers[provider];
	return providerConfig && typeof providerConfig === "object"
		? { ...providerConfig }
		: {};
}

export function writeByokConfig(config) {
	if (!BYOK_STORAGE_KEY) return false;
	const providers = config?.providers;
	if (!providers || typeof providers !== "object" || Array.isArray(providers)) {
		return false;
	}
	localStorage.setItem(
		BYOK_STORAGE_KEY,
		JSON.stringify({ providers: { ...providers } }),
	);
	return true;
}

export function encodeByokConfig() {
	return btoa(encodeURIComponent(JSON.stringify(getByokConfig())));
}

export function clearUserScopedStorage() {
	if (!storageNamespace) return;
	for (let index = localStorage.length - 1; index >= 0; index -= 1) {
		const key = localStorage.key(index);
		if (key?.startsWith(`${storageNamespace}_`)) {
			localStorage.removeItem(key);
		}
	}
}
