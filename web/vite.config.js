import { resolve } from "node:path";

import { defineConfig } from "vite";

const entry = (name) => resolve(import.meta.dirname, name);

// Clean-route -> MPA entry mapping. Mirrors the backend SPA routes in
// main.py so the same URLs work in dev, local single-origin, and the
// Phase 4 static-host deployment.
const ROUTE_ENTRIES = {
	"/": "index.html",
	"/login": "login.html",
	"/chat": "chat.html",
	"/config": "config.html",
	"/about": "about.html",
};

function mpaFallback() {
	return {
		name: "mpa-clean-route-fallback",
		configureServer(server) {
			server.middlewares.use((req, _res, next) => {
				if (req.method !== "GET") return next();
				const pathname = new URL(req.url, "http://localhost").pathname;
				let entryName = ROUTE_ENTRIES[pathname];
				// /chat/{session_id} deep links resolve to the chat entry; the
				// SPA reads the session id from the path on boot.
				if (!entryName && pathname.startsWith("/chat/")) {
					entryName = "chat.html";
				}
				if (entryName) {
					req.url = `/${entryName}`;
				}
				next();
			});
		},
	};
}

// Multi-page SPA: one HTML entry per page. The backend serves the built
// web/dist in local single-origin mode; a static host (Phase 4) rewrites
// /chat/* and friends to these entries.
export default defineConfig({
	base: "/",
	plugins: [mpaFallback()],
	build: {
		outDir: "dist",
		rollupOptions: {
			input: {
				home: entry("index.html"),
				login: entry("login.html"),
				chat: entry("chat.html"),
				config: entry("config.html"),
				about: entry("about.html"),
			},
		},
	},
	server: {
		port: 5173,
		proxy: {
			// Everything under /api (v1 routes plus the /api/auth OAuth callback
			// compatibility path) proxies to the local FastAPI backend.
			"/api": {
				target: "http://localhost:5000",
				changeOrigin: true,
			},
		},
	},
});
