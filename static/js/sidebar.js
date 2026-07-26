// FILE: static/js/sidebar.js
// DESCRIPTION: Unified sidebar management with session actions

// === GLOBAL FETCH INTERCEPTOR (auth gate + Phase 3 BYOK) ===
(() => {
	const metaUserId =
		document.querySelector('meta[name="user-id"]')?.content || "default";
	window.BYOK_STORAGE_KEY = `yuzu_byok_config_${metaUserId}`;

	const legacyConfig = localStorage.getItem("yuzu_byok_config");
	if (legacyConfig) {
		if (!localStorage.getItem(window.BYOK_STORAGE_KEY)) {
			localStorage.setItem(window.BYOK_STORAGE_KEY, legacyConfig);
		}
		localStorage.removeItem("yuzu_byok_config");
	}

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
				const raw = localStorage.getItem(window.BYOK_STORAGE_KEY);
				if (raw) {
					init.headers.set("X-BYOK-Config", btoa(encodeURIComponent(raw)));
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
				<button class="auth-btn auth-google-btn" onclick="loginWith('google')">${_GOOGLE_SVG} Sign in with Google</button>
				<button class="auth-btn auth-github-btn" onclick="loginWith('github')">${_GITHUB_SVG} Sign in with GitHub</button>
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

if (typeof window.initCustomScrollbars === "function") {
	window.initCustomScrollbars(document.getElementById("mainSidebar"));
}
const _GOOGLE_SVG = `<svg viewBox="0 0 24 24" width="20" height="20"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>`;
const _GITHUB_SVG = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.565 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/></svg>`;

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
			<button class="auth-logout-btn" onclick="handleLogout()">Sign Out</button>
		</div>
	`;
}

function _renderUnauthenticated(container) {
	container.innerHTML = `
		<div class="auth-login-buttons">
			<button class="auth-btn auth-google-btn" onclick="loginWith('google')">${_GOOGLE_SVG} Sign in with Google</button>
			<button class="auth-btn auth-github-btn" onclick="loginWith('github')">${_GITHUB_SVG} Sign in with GitHub</button>
		</div>
	`;
}

function loginWith(provider) {
	window.location.href = `/api/auth/login?provider=${provider}`;
}

async function handleLogout() {
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
	localStorage.setItem("yuzu-theme", theme);
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
				renameBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;
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
					deleteBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`;
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
				if (window.router) {
					window.router.updateUrl(data.session_id);
				}
				if (
					window.location.pathname === "/chat" &&
					window.handleSessionSwitch
				) {
					void window.handleSessionSwitch(data.session_id);
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

	// Dynamic import to avoid module issues outside module scripts
	if (window.eventRouter && window.router) {
		const currentSession = window.router.currentSessionId;
		if (
			currentSession &&
			window.chatStore?.isGenerating &&
			window.chatStore.sessionId === currentSession
		) {
			console.log(
				`[Sidebar] Active stream in session ${currentSession}, pausing`,
			);
		}
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

	// Cancel any active stream for current session before switching
	if (window.eventRouter && window.router?.currentSessionId) {
		window.eventRouter.cancelStream(window.router.currentSessionId);
	}

	if (window.handleSessionSwitch) {
		window
			.handleSessionSwitch(sessionId)
			.then(() => {
				toggleSidebar();
			})
			.catch(() => showNotification("Failed to switch session", "error"))
			.finally(() => {
				_isSessionSwitching = false;
				_setSessionSwitchingVisual(sessionId, false);
			});
		return;
	}

	_isSessionSwitching = false;
	_setSessionSwitchingVisual(sessionId, false);
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
		localStorage.getItem("yuzu-theme") || "stellar-night-suisei";
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

function syncActiveSidebarItem(sessionId) {
	const list = document.getElementById("sidebarSessionsList");
	if (!list) return;
	for (const item of list.querySelectorAll(".sidebar-session-item")) {
		const id = item.getAttribute("data-session-id");
		item.classList.toggle("active", String(id) === String(sessionId));
	}
}

window.toggleSidebar = toggleSidebar;
window.switchTheme = switchTheme;
window.createNewSession = createNewSession;
window.switchSession = switchSession;
window.renameSessionPrompt = renameSessionPrompt;
window.renameSession = renameSession;
window.deleteSessionPrompt = deleteSessionPrompt;
window.deleteSession = deleteSession;
window.loadSidebarSessions = loadSidebarSessions;
window.syncActiveSidebarItem = syncActiveSidebarItem;
window.loginWith = loginWith;
window.handleLogout = handleLogout;
