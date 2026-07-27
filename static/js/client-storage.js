const userId = document.querySelector('meta[name="user-id"]')?.content || "";
const storageNamespace = userId ? `user_${userId}` : "";

export const BYOK_STORAGE_KEY = storageNamespace
	? `${storageNamespace}_api_keys`
	: "";
export const USER_THEME_STORAGE_KEY = storageNamespace
	? `${storageNamespace}_theme`
	: "";

export function getUserStorageKey(suffix) {
	return storageNamespace ? `${storageNamespace}_${suffix}` : "";
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
