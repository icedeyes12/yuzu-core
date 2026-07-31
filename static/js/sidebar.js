// FILE: static/js/sidebar.js
// DESCRIPTION: Unified sidebar management with session actions

import {
	clearUserScopedStorage,
	encodeByokConfig,
	USER_THEME_STORAGE_KEY,
} from "./client-storage.js";
import { eventRouter } from "./modules/event-router.js";
import { router } from "./modules/router.js";
import { chatStore } from "./modules/store.js";
import { renderRuntimeIcon } from "./runtime-icon-renderer.js";
import { handleSessionSwitch } from "./session-controller.js";

// === GLOBAL FETCH INTERCEPTOR (auth gate + Phase 3 BYOK) ===
(() => {
	const _origFetch = window.fetch;
	const _LLM_ENDPOINTS = [
		"/api/send_message",
		"/api/send_message_stream",
		"/api/generate_image",
	];

	window.fetch = async function (input, init) {
		init = init || {};
		init.headers = new Headers(init.headers || {});

		const url = typeof input === "string" ? input : input.url;

		if (_LLM_ENDPOINTS.some((ep) => url.includes(ep))) {
			try {
				const encoded = encodeByokConfig();
				if (encoded) {
					init.headers.set("X-BYOK-Config", encoded);
				}
			} catch (_e) {
				// BYOK settings are optional; continue without them.
			}
		}

		const response = await _origFetch.call(this, input, init);

		if (
			(response.status === 401 || response.status === 403) &&
			url.includes("/api/")
		) {
			if (window.location.pathname !== "/login") {
				window.location.href = "/login";
			}
		}
		return response;
	};
})();

function _ensureAuthOverlay() {
	let overlay = document.getElementById("authOverlay");
	if (overlay) return overlay;

	overlay = document.createElement("div");
	overlay.className = "auth-overlay";
	overlay.id = "authOverlay";
	overlay.innerHTML = `
		<div class="auth-overlay-card">
			<h2>Session Expired</h2>
			<p>Please sign in again to continue.</p>
			<div class="auth-overlay-buttons">
				<button class="auth-btn auth-google-btn" data-auth-provider="google">${_GOOGLE_SVG} Sign in with Google</button>
				<button class="auth-btn auth-github-btn" data-auth-provider="github">${_GITHUB_SVG} Sign in with GitHub</button>
			</div>
		</div>
	`;
	document.body.appendChild(overlay);
	return overlay;
}

function _showAuthOverlay() {
	const overlay = _ensureAuthOverlay();
	overlay.classList.add("active");
}
function _hideAuthOverlay() {
	const overlay = document.getElementById("authOverlay");
	if (overlay) overlay.classList.remove("active");
}

const _GOOGLE_SVG =
	'<img class="auth-provider-logo" src="/static/assets/logos/providers/google.svg" width="20" height="20" alt="" aria-hidden="true">';
const _GITHUB_SVG =
	'<img class="auth-provider-logo" src="/static/assets/logos/providers/github.svg" width="20" height="20" alt="" aria-hidden="true">';

function _injectAuthSection() {
	const sidebar = document.getElementById("mainSidebar");
	if (!sidebar) return;
	if (document.getElementById("authSection")) return;

	const content = sidebar.querySelector(".sidebar-content");
	if (!content) return;

	const authSection = document.createElement("div");
	authSection.className = "sidebar-section auth-section";
	authSection.id = "authSection";
	authSection.innerHTML = `
		<h3>Account</h3>
		<div class="auth-content" id="authContent">
			<div class="auth-loading">Checking session…</div>
		</div>
	`;
	content.appendChild(authSection);
}

async function _checkAuthState() {
	const authContent = document.getElementById("authContent");
	if (!authContent) return;

	try {
		const resp = await fetch("/api/auth/me", {
			headers: { Accept: "application/json" },
		});
		if (!resp.ok) {
			_renderUnauthenticated(authContent);
			return;
		}
		const data = await resp.json();
		_renderAuthenticated(authContent, data);
		_hideAuthOverlay();
	} catch (_e) {
		_renderUnauthenticated(authContent);
	}
}

function _renderAuthenticated(container, data) {
	const userId = data?.user_id || "";
	const email = data?.email || "";
	const displayName = data?.user_name || "";
	const avatarUrl = data?.avatar_url || "";
	const shortId = userId ? `${userId.slice(0, 8)}…` : "unknown";
	const showName = displayName || email || shortId;
	const safeAvatarUrl =
		avatarUrl && /^(https?:|data:)/i.test(avatarUrl) ? avatarUrl : "";
	const avatarHtml = safeAvatarUrl
		? `<img class="auth-user-avatar" src="${safeAvatarUrl}" alt="avatar" referrerpolicy="no-referrer" />`
		: `<div class="auth-user-avatar auth-avatar-placeholder">${_escapeHtml((showName[0] || "?").toUpperCase())}</div>`;
	container.innerHTML = `
		<div class="auth-user">
			<div class="auth-user-info">
				${avatarHtml}
				<div class="auth-user-meta">
					<div class="auth-user-name" title="${_escapeHtml(showName)}">${_escapeHtml(showName)}</div>
					<div class="auth-user-email" title="${_escapeHtml(email)}">${_escapeHtml(email || "")}</div>
				</div>
			</div>
			<button class="auth-logout-btn" data-action="logout">Sign Out</button>
		</div>
	`;
}

function _renderUnauthenticated(container) {
	container.innerHTML = `
		<div class="auth-login-buttons">
			<button class="auth-btn auth-google-btn" data-auth-provider="google">${_GOOGLE_SVG} Sign in with Google</button>
			<button class="auth-btn auth-github-btn" data-auth-provider="github">${_GITHUB_SVG} Sign in with GitHub</button>
		</div>
	`;
}

function loginWith(provider) {
	window.location.href = `/api/auth/login?provider=${provider}`;
}

function clearUserScopedClientState() {
	clearUserScopedStorage();
}

async function handleLogout() {
	clearUserScopedClientState();
	try {
		await fetch("/api/auth/logout", { method: "POST" });
	} catch (_e) {
		// Ignore error on logout
	}
	_hideAuthOverlay();
	window.location.href = "/login";
}

function _initAuth() {
	_injectAuthSection();
	_checkAuthState();
}

let _currentTheme = "stellar-night-suisei";
let _isSessionSwitching = false;
let _sessionSwitchCooldown = false;
const SESSION_SWITCH_DEBOUNCE_MS = 300;

function toggleSidebar() {
	const sidebar = document.getElementById("mainSidebar");
	const overlay = document.getElementById("sidebarOverlay");
	const hamburger = document.getElementById("hamburgerMenu");
	if (!sidebar || !overlay || !hamburger) return;

	if (sidebar.classList.contains("open")) {
		sidebar.classList.remove("open");
		overlay.classList.remove("active");
		hamburger.classList.remove("active");
	} else {
		sidebar.classList.add("open");
		overlay.classList.add("active");
		hamburger.classList.add("active");
		loadSidebarSessions();
	}
	hamburger.setAttribute(
		"aria-expanded",
		String(sidebar.classList.contains("open")),
	);
}

function initCustomDropdown() {
	const dropdown = document.getElementById("themeDropdown");
	if (!dropdown) return;

	const selected = dropdown.querySelector(".dropdown-selected");
	const options = dropdown.querySelector(".dropdown-options");
	const optionItems = dropdown.querySelectorAll(".dropdown-option");
	if (!selected || !options) return;

	selected.addEventListener("click", (e) => {
		e.stopPropagation();
		const isActive = options.classList.contains("active");
		for (const opt of document.querySelectorAll(".dropdown-options.active")) {
			if (opt !== options) opt.classList.remove("active");
		}
		for (const sel of document.querySelectorAll(".dropdown-selected.active")) {
			if (sel !== selected) sel.classList.remove("active");
		}
		options.classList.toggle("active", !isActive);
		selected.classList.toggle("active", !isActive);
	});

	for (const option of optionItems) {
		option.addEventListener("click", function () {
			const value = this.getAttribute("data-value");
			const text = this.textContent.trim();
			const selectedText = selected.querySelector(".selected-text");
			if (selectedText) selectedText.textContent = text;
			for (const opt of optionItems) {
				opt.classList.remove("active");
			}
			this.classList.add("active");
			options.classList.remove("active");
			selected.classList.remove("active");
			switchTheme(value);
		});
	}

	document.addEventListener("click", () => {
		options.classList.remove("active");
		selected.classList.remove("active");
	});
}

function switchTheme(theme) {
	_currentTheme = theme;
	document.body.setAttribute("data-theme", theme);
	const dropdown = document.getElementById("themeDropdown");
	if (dropdown) {
		const option = dropdown.querySelector(`[data-value="${theme}"]`);
		if (option) {
			const text = option.textContent.trim();
			const selectedText = dropdown.querySelector(".selected-text");
			if (selectedText) selectedText.textContent = text;
			for (const opt of dropdown.querySelectorAll(".dropdown-option")) {
				opt.classList.remove("active");
			}
			option.classList.add("active");
		}
	}
	if (USER_THEME_STORAGE_KEY) {
		localStorage.setItem(USER_THEME_STORAGE_KEY, theme);
	}
}

function showSessionsSkeleton() {
	const sessionsList = document.getElementById("sidebarSessionsList");
	if (!sessionsList) return;
	sessionsList.innerHTML = `
		<li class="loading" role="status" aria-live="polite">Loading sessions...</li>
	`;
}

function loadSidebarSessions() {
	const sessionSection = document.getElementById("sessionSection");
	const sessionsList = document.getElementById("sidebarSessionsList");
	if (!sessionSection || !sessionsList) return;

	sessionSection.classList.add("is-visible");
	showSessionsSkeleton();

	fetch("/api/sessions/list", {
		headers: { Accept: "application/json" },
	})
		.then((response) => {
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			return response.json();
		})
		.then((data) => {
			sessionsList.innerHTML = "";
			const sessions = Array.isArray(data.sessions) ? data.sessions : [];
			if (sessions.length === 0) {
				sessionsList.innerHTML = '<li class="no-sessions">No sessions yet</li>';
				return;
			}

			const urlParts = window.location.pathname.split("/").filter((p) => p);
			const urlSessionId =
				urlParts.length >= 2 && urlParts[0] === "chat" ? urlParts[1] : null;

			for (const session of sessions) {
				const sessionItem = document.createElement("li");
				const isCurrentSession = String(session.id) === String(urlSessionId);
				sessionItem.className = `sidebar-session-item ${isCurrentSession ? "active" : ""}`;
				sessionItem.setAttribute("data-session-id", session.id);

				const sessionContent = document.createElement("div");
				sessionContent.className = "session-content";
				sessionContent.onclick = () => switchSession(session.id);

				const sessionName = document.createElement("div");
				sessionName.className = "sidebar-session-name";
				sessionName.textContent = session.name || "Untitled Chat";

				const sessionMeta = document.createElement("div");
				sessionMeta.className = "sidebar-session-meta";
				sessionMeta.textContent = `${session.message_count || 0} messages • ${formatSessionDate(session.updated_at)}`;

				sessionContent.appendChild(sessionName);
				sessionContent.appendChild(sessionMeta);

				const sessionActions = document.createElement("div");
				sessionActions.className = "session-actions";

				const renameBtn = document.createElement("button");
				renameBtn.type = "button";
				renameBtn.className = "session-action-btn rename-btn";
				renameBtn.title = "Rename session";
				renameBtn.innerHTML = renderRuntimeIcon("edit", { size: 14 }) || "";
				renameBtn.onclick = (e) => {
					e.stopPropagation();
					renameSessionPrompt(session.id, session.name);
				};
				sessionActions.appendChild(renameBtn);

				if (!session.is_active) {
					const deleteBtn = document.createElement("button");
					deleteBtn.type = "button";
					deleteBtn.className = "session-action-btn delete-btn";
					deleteBtn.title = "Delete session";
					deleteBtn.innerHTML = renderRuntimeIcon("trash", { size: 14 }) || "";
					deleteBtn.onclick = (e) => {
						e.stopPropagation();
						deleteSessionPrompt(session.id);
					};
					sessionActions.appendChild(deleteBtn);
				}

				sessionItem.appendChild(sessionContent);
				sessionItem.appendChild(sessionActions);
				sessionsList.appendChild(sessionItem);
			}
		})
		.catch((_error) => {
			sessionsList.innerHTML = '<li class="error">Failed to load sessions</li>';
		});
}

function renameSessionPrompt(sessionId, currentName) {
	const newName = prompt("Enter new session name:", currentName);
	if (newName?.trim() && newName !== currentName) {
		renameSession(sessionId, newName.trim());
	}
}

function renameSession(sessionId, newName) {
	fetch("/api/sessions/rename", {
		method: "POST",
		headers: { "Content-Type": "application/json", Accept: "application/json" },
		body: JSON.stringify({ session_id: sessionId, name: newName }),
	})
		.then((response) => {
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			return response.json();
		})
		.then((data) => {
			if (data.status === "success") {
				loadSidebarSessions();
				const sessionNameElement = document.getElementById("sessionName");
				if (sessionNameElement) {
					fetch("/api/profile", { headers: { Accept: "application/json" } })
						.then((response) => {
							if (!response.ok) throw new Error(`HTTP ${response.status}`);
							return response.json();
						})
						.then((profileData) => {
							if (
								profileData.active_session &&
								profileData.active_session.id === sessionId
							) {
								sessionNameElement.textContent = newName;
							}
						});
				}
				showNotification("Session renamed successfully!", "success");
			} else {
				showNotification("Failed to rename session", "error");
			}
		})
		.catch(() => {
			showNotification("Error renaming session", "error");
		});
}

function deleteSessionPrompt(sessionId) {
	if (
		confirm(
			"Are you sure you want to delete this session? This action cannot be undone.",
		)
	) {
		deleteSession(sessionId);
	}
}

function deleteSession(sessionId) {
	fetch("/api/sessions/delete", {
		method: "POST",
		headers: { "Content-Type": "application/json", Accept: "application/json" },
		body: JSON.stringify({ session_id: sessionId }),
	})
		.then((response) => {
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			return response.json();
		})
		.then((data) => {
			if (data.status === "success") {
				loadSidebarSessions();
				showNotification("Session deleted successfully!", "success");
			} else {
				showNotification("Failed to delete session", "error");
			}
		})
		.catch(() => {
			showNotification("Error deleting session", "error");
		});
}

function createNewSession() {
	fetch("/api/sessions/create", {
		method: "POST",
		headers: { "Content-Type": "application/json", Accept: "application/json" },
		body: JSON.stringify({ name: "New Chat" }),
	})
		.then((response) => {
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			return response.json();
		})
		.then((data) => {
			if (data.status === "success") {
				loadSidebarSessions();
				toggleSidebar();
				router.updateUrl(data.session_id);
				if (window.location.pathname === "/chat") {
					void handleSessionSwitch(data.session_id);
				} else {
					window.location.href = "/chat";
				}
			}
		})
		.catch(() => {
			showNotification("Failed to create new session", "error");
		});
}

function switchSession(sessionId) {
	if (_sessionSwitchCooldown || _isSessionSwitching) return;

	const currentSession = router.currentSessionId;
	if (
		currentSession &&
		chatStore.isGenerating &&
		chatStore.sessionId === currentSession
	) {
		console.log(
			`[Sidebar] Active stream in session ${currentSession}, pausing`,
		);
	}

	const isOnChatPage = window.location.pathname.startsWith("/chat");
	if (!isOnChatPage) {
		window.location.href = `/chat/${sessionId}`;
		toggleSidebar();
		return;
	}

	_sessionSwitchCooldown = true;
	setTimeout(() => {
		_sessionSwitchCooldown = false;
	}, SESSION_SWITCH_DEBOUNCE_MS);

	_isSessionSwitching = true;
	_setSessionSwitchingVisual(sessionId, true);
	if (router.currentSessionId) {
		eventRouter.cancelStream(router.currentSessionId);
	}

	handleSessionSwitch(sessionId)
		.then(() => toggleSidebar())
		.catch(() => showNotification("Failed to switch session", "error"))
		.finally(() => {
			_isSessionSwitching = false;
			_setSessionSwitchingVisual(sessionId, false);
		});
}

function _setSessionSwitchingVisual(_sessionId, isLoading) {
	const sessionsList = document.getElementById("sidebarSessionsList");
	if (!sessionsList) return;

	for (const item of sessionsList.querySelectorAll(".sidebar-session-item")) {
		item.classList.remove("switching");
	}

	if (isLoading) {
		sessionsList.classList.add("switching-active");
	} else {
		sessionsList.classList.remove("switching-active");
	}
}

function _escapeHtml(text) {
	const div = document.createElement("div");
	div.textContent = String(text ?? "");
	return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

function formatSessionDate(dateString) {
	const date = new Date(dateString);
	const now = new Date();
	const diffTime = Math.abs(now - date);
	const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

	if (diffDays === 1) return "Today";
	if (diffDays === 2) return "Yesterday";
	if (diffDays <= 7) return `${diffDays - 1} days ago`;
	return date.toLocaleDateString();
}

function showNotification(message, type = "info") {
	const existingNotification = document.querySelector(".session-notification");
	if (existingNotification) existingNotification.remove();

	const notification = document.createElement("div");
	notification.className = `session-notification ${type}`;
	notification.textContent = message;
	document.body.appendChild(notification);
	setTimeout(() => {
		if (notification.parentNode) {
			notification.parentNode.removeChild(notification);
		}
	}, 3000);
}

document.addEventListener("DOMContentLoaded", () => {
	const savedTheme =
		(USER_THEME_STORAGE_KEY
			? localStorage.getItem(USER_THEME_STORAGE_KEY)
			: null) || "stellar-night-suisei";
	document.body.setAttribute("data-theme", savedTheme);
	_currentTheme = savedTheme;
	initCustomDropdown();
	const dropdown = document.getElementById("themeDropdown");
	if (dropdown) {
		const option = dropdown.querySelector(`[data-value="${savedTheme}"]`);
		if (option) {
			const text = option.textContent.trim();
			const selectedText = dropdown.querySelector(".selected-text");
			if (selectedText) selectedText.textContent = text;
			for (const opt of dropdown.querySelectorAll(".dropdown-option")) {
				opt.classList.remove("active");
			}
			option.classList.add("active");
		}
	}
	_initAuth();
	loadSidebarSessions();
});

function handleSidebarAction(event) {
	const actionTarget = event.target.closest(
		"[data-action], [data-auth-provider]",
	);
	if (!actionTarget) return;
	const action = actionTarget.dataset.action;
	if (action === "toggle-sidebar" || action === "close-sidebar") {
		toggleSidebar();
		return;
	}
	if (action === "create-session") {
		createNewSession();
		return;
	}
	if (action === "logout") {
		void handleLogout();
		return;
	}
	if (actionTarget.dataset.authProvider) {
		loginWith(actionTarget.dataset.authProvider);
	}
}

document.addEventListener("click", handleSidebarAction);

export {
	createNewSession,
	deleteSession,
	handleLogout,
	loadSidebarSessions,
	loginWith,
	renameSession,
	switchSession,
	switchTheme,
	toggleSidebar,
};
