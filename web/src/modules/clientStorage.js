// Storage namespace is resolved lazily from /api/v1/auth/me instead of a
// server-rendered <meta name="user-id"> tag, so module state is mutable.
let storageNamespace = "";

export function setStorageNamespace(userId) {
	storageNamespace = userId ? `user_${userId}` : "";
	return storageNamespace;
}

export function getStorageNamespace() {
	return storageNamespace;
}

export function getByokStorageKey() {
	return storageNamespace ? `${storageNamespace}_api_keys` : "";
}

export function getUserThemeStorageKey() {
	return storageNamespace ? `${storageNamespace}_theme` : "";
}

export function getUserStorageKey(suffix) {
	return storageNamespace ? `${storageNamespace}_${suffix}` : "";
}

export const DEFAULT_YUZU_PORTAL_BASE_URL = "http://localhost:20128/v1";

export function maskApiKey(value) {
	if (typeof value !== "string" || !value) return "";
	if (value.length <= 8) return "*".repeat(value.length);
	return `${value.slice(0, 8)}...${value.slice(-4)}`;
}

export function getByokConfig() {
	const key = getByokStorageKey();
	if (!key) return { providers: {} };
	try {
		const raw = localStorage.getItem(key);
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
	const key = getByokStorageKey();
	if (!key) return false;
	const providers = config?.providers;
	if (!providers || typeof providers !== "object" || Array.isArray(providers)) {
		return false;
	}
	localStorage.setItem(key, JSON.stringify({ providers: { ...providers } }));
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
