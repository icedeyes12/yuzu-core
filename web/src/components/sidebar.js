import { apiFetch, apiUrl } from "../modules/apiFetch.js";
import { bootstrapAuth, getCachedMe } from "../modules/authBootstrap.js";
import { clearUserScopedStorage } from "../modules/clientStorage.js";
import { eventRouter } from "../modules/event-router.js";
import {
	aboutUrl,
	chatUrl,
	configUrl,
	homeUrl,
	loginUrl,
} from "../modules/links.js";
import { router } from "../modules/router.js";
import { handleSessionSwitch } from "../modules/session-controller.js";
import { chatStore } from "../modules/store.js";
import { applyTheme, getSavedTheme, persistTheme } from "../modules/theme.js";

let _isSessionSwitching = false;
let _sessionSwitchCooldown = false;
const SESSION_SWITCH_DEBOUNCE_MS = 300;

const THEME_OPTIONS = [
	{ value: "dark", label: "Dark Blue" },
	{ value: "light", label: "Soft Light" },
	{ value: "stellar-night-suisei", label: "Stellar Night (Suisei Edition)" },
	{ value: "tokyonight", label: "Tokyo Night" },
	{ value: "lavender", label: "Pastel Lavender" },
	{ value: "mint", label: "Pastel Mint" },
	{ value: "peach", label: "Pastel Peach" },
	{ value: "dark-lavender", label: "Dark Lavender" },
	{ value: "vanilla-orange", label: "Vanilla Orange" },
];

const _GOOGLE_SVG =
	'<img class="auth-provider-logo" src="/assets/logos/providers/google.svg" width="20" height="20" alt="" aria-hidden="true">';
const _GITHUB_SVG =
	'<img class="auth-provider-logo" src="/assets/logos/providers/github.svg" width="20" height="20" alt="" aria-hidden="true">';

function sidebarMarkup() {
	const themeOptions = THEME_OPTIONS.map(
		(option) => `
			<div class="dropdown-option" data-value="${option.value}" role="option" tabindex="0">
				<span class="theme-preview ${option.value}-preview" aria-hidden="true"></span>
				${option.label}
			</div>`,
	).join("");

	return `
<aside class="sidebar" id="mainSidebar" aria-label="Application sidebar">
  <div class="sidebar-header">
    <h2>Yuzu Companion</h2>
    <button class="close-sidebar" data-action="toggle-sidebar" aria-label="Close sidebar" type="button">×</button>
  </div>

  <div class="sidebar-content">
    <nav class="sidebar-section" aria-label="Main navigation">
      <h3>Navigation</h3>
      <a href="${chatUrl()}" class="sidebar-link chat-link" data-action="toggle-sidebar">
        <span class="sidebar-icon chat-icon" aria-hidden="true"></span> Chat
      </a>
      <a href="${homeUrl()}" class="sidebar-link home-link" data-action="toggle-sidebar">
        <span class="sidebar-icon home-icon" aria-hidden="true"></span> Home
      </a>
    </nav>

    <section class="sidebar-section" aria-label="Theme selector">
      <h3>Theme</h3>
      <div class="custom-dropdown" id="themeDropdown" role="listbox" aria-label="Select theme">
        <button class="dropdown-selected" type="button" aria-haspopup="listbox" aria-expanded="false">
          <span class="selected-text">Stellar Night</span>
          <span class="dropdown-arrow" aria-hidden="true">▼</span>
        </button>
        <div class="dropdown-options" role="listbox">
          ${themeOptions}
        </div>
      </div>
    </section>

    <section class="sidebar-section sidebar-section--sessions" id="sessionSection" aria-label="Chat sessions">
      <h3>Conversations</h3>
      <button class="sidebar-btn" type="button" data-action="create-session" aria-label="Start a new conversation">
        <span class="sidebar-icon add-icon" aria-hidden="true"></span> New conversation
      </button>
      <ul class="sessions-list" id="sidebarSessionsList" aria-label="Session list">
        <li class="loading" role="status" aria-live="polite">Loading sessions...</li>
      </ul>
    </section>

    <nav class="sidebar-section sidebar-section--secondary" aria-label="Application navigation">
      <h3>More</h3>
      <a href="${configUrl()}" class="sidebar-link config-link" data-action="toggle-sidebar">
        <span class="sidebar-icon config-icon" aria-hidden="true"></span> Config
      </a>
      <a href="${aboutUrl()}" class="sidebar-link about-link" data-action="toggle-sidebar">
        <span class="sidebar-icon about-icon" aria-hidden="true"></span> About
      </a>
    </nav>
  </div>
</aside>

<div class="sidebar-overlay" id="sidebarOverlay" data-action="toggle-sidebar" aria-hidden="true"></div>`;
}

function escapeHtml(value) {
	return String(value).replace(
		/[&<>"']/g,
		(character) =>
			({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
				character
			],
	);
}

export function toggleSidebar() {
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

	selected.addEventListener("click", (event) => {
		event.stopPropagation();
		const isActive = options.classList.contains("active");
		for (const open of document.querySelectorAll(".dropdown-options.active")) {
			if (open !== options) open.classList.remove("active");
		}
		for (const open of document.querySelectorAll(".dropdown-selected.active")) {
			if (open !== selected) open.classList.remove("active");
		}
		options.classList.toggle("active", !isActive);
		selected.classList.toggle("active", !isActive);
	});

	for (const option of optionItems) {
		option.addEventListener("click", function () {
			const value = this.getAttribute("data-value");
			switchTheme(value);
			options.classList.remove("active");
			selected.classList.remove("active");
		});
	}

	document.addEventListener("click", () => {
		options.classList.remove("active");
		selected.classList.remove("active");
	});
}

function switchTheme(theme) {
	applyTheme(theme);
	persistTheme(theme);
	const dropdown = document.getElementById("themeDropdown");
	if (!dropdown) return;
	const option = dropdown.querySelector(`[data-value="${theme}"]`);
	const selectedText = dropdown.querySelector(".selected-text");
	if (option && selectedText) {
		selectedText.textContent = option.textContent.trim();
	}
	for (const item of dropdown.querySelectorAll(".dropdown-option")) {
		item.classList.remove("active");
	}
	if (option) option.classList.add("active");
}

function syncThemeDropdown() {
	const theme = getSavedTheme();
	applyTheme(theme);
	const dropdown = document.getElementById("themeDropdown");
	if (!dropdown) return;
	const option = dropdown.querySelector(`[data-value="${theme}"]`);
	const selectedText = dropdown.querySelector(".selected-text");
	if (option && selectedText) {
		selectedText.textContent = option.textContent.trim();
	}
	for (const item of dropdown.querySelectorAll(".dropdown-option")) {
		item.classList.remove("active");
	}
	if (option) option.classList.add("active");
}

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

function renderAuthenticated(container, data) {
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
		: `<div class="auth-user-avatar auth-avatar-placeholder">${escapeHtml(
				(showName[0] || "?").toUpperCase(),
			)}</div>`;
	container.innerHTML = `
		<div class="auth-user">
			<div class="auth-user-info">
				${avatarHtml}
				<div class="auth-user-meta">
					<div class="auth-user-name" title="${escapeHtml(showName)}">${escapeHtml(showName)}</div>
					<div class="auth-user-email" title="${escapeHtml(email)}">${escapeHtml(email || "")}</div>
				</div>
			</div>
			<button class="auth-logout-btn" data-action="logout">Sign Out</button>
		</div>
	`;
}

/**
 * Renders sign-in options for unauthenticated users.
 * @param {HTMLElement} container - The element where the sign-in options are inserted.
 */
function renderUnauthenticated(container) {
	container.innerHTML = `
		<div class="auth-login-buttons">
			<a class="auth-btn auth-google-btn" href="${apiUrl("/api/v1/auth/login?provider=google")}">${_GOOGLE_SVG} Sign in with Google</a>
			<a class="auth-btn auth-github-btn" href="${apiUrl("/api/v1/auth/login?provider=github")}">${_GITHUB_SVG} Sign in with GitHub</a>
		</div>
	`;
}

/**
 * Renders the authenticated or unauthenticated account section.
 */
async function renderAuthSection() {
	const authContent = document.getElementById("authContent");
	if (!authContent) return;

	const me =
		getCachedMe() || (await bootstrapAuth({ redirectOnUnauthorized: false }));
	if (me) {
		renderAuthenticated(authContent, me);
	} else {
		renderUnauthenticated(authContent);
	}
}

/**
 * Signs the user out, clears user-scoped storage, and redirects to the login page.
 */
async function handleLogout() {
	clearUserScopedStorage();
	try {
		await apiFetch("/api/v1/auth/logout", { method: "POST" });
	} catch {
		// Ignore errors on logout; the session cookie is cleared on the server.
	}
	window.location.assign(loginUrl());
}

/**
 * Displays a temporary session notification.
 * @param {string} message - The notification message.
 * @param {string} [type="info"] - The notification style type.
 */
function showNotification(message, type = "info") {
	const existing = document.querySelector(".session-notification");
	if (existing) existing.remove();

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

function loadSidebarSessions() {
	const sessionSection = document.getElementById("sessionSection");
	const sessionsList = document.getElementById("sidebarSessionsList");
	if (!sessionSection || !sessionsList) return;

	sessionSection.classList.add("is-visible");
	sessionsList.innerHTML =
		'<li class="loading" role="status" aria-live="polite">Loading sessions...</li>';

	apiFetch("/api/v1/sessions/list", { headers: { Accept: "application/json" } })
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
			const params = new URLSearchParams(window.location.search);
			const currentSessionId = urlSessionId || params.get("session") || null;

			for (const session of sessions) {
				const sessionItem = document.createElement("li");
				const isCurrentSession =
					String(session.id) === String(currentSessionId);
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
				renameBtn.textContent = "✎";
				renameBtn.onclick = (event) => {
					event.stopPropagation();
					renameSessionPrompt(session.id, session.name);
				};
				sessionActions.appendChild(renameBtn);

				if (!session.is_active) {
					const deleteBtn = document.createElement("button");
					deleteBtn.type = "button";
					deleteBtn.className = "session-action-btn delete-btn";
					deleteBtn.title = "Delete session";
					deleteBtn.textContent = "🗑";
					deleteBtn.onclick = (event) => {
						event.stopPropagation();
						deleteSessionPrompt(session.id);
					};
					sessionActions.appendChild(deleteBtn);
				}

				sessionItem.appendChild(sessionContent);
				sessionItem.appendChild(sessionActions);
				sessionsList.appendChild(sessionItem);
			}
		})
		.catch(() => {
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
	apiFetch("/api/v1/sessions/rename", {
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
	apiFetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
		method: "DELETE",
		headers: { Accept: "application/json" },
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
	apiFetch("/api/v1/sessions/create", {
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
				if (window.location.pathname.startsWith("/chat")) {
					void handleSessionSwitch(data.session_id);
				} else {
					window.location.assign(chatUrl(data.session_id));
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
		window.location.assign(chatUrl(sessionId));
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
}

/**
 * Mount the shared sidebar into #sidebarRoot and wire its behaviors.
 */
export function mountSidebar() {
	const root = document.getElementById("sidebarRoot");
	if (!root || document.getElementById("mainSidebar")) return;
	root.innerHTML = sidebarMarkup();

	const page = document.body.dataset.page || "";
	const currentLink = document.querySelector(`.sidebar-link.${page}-link`);
	if (currentLink) {
		currentLink.classList.add("active");
		currentLink.setAttribute("aria-current", "page");
	}

	syncThemeDropdown();
	initCustomDropdown();
	_injectAuthSection();
	void renderAuthSection();
	loadSidebarSessions();

	document.addEventListener("keydown", (event) => {
		if (event.key !== "Escape") return;
		const sidebar = document.getElementById("mainSidebar");
		if (sidebar?.classList.contains("open")) toggleSidebar();
	});
	document.addEventListener("click", handleSidebarAction);
}
