// FILE: static/js/home.js
// DESCRIPTION: Minimal entry-point behavior for the home page

import { toggleSidebar } from "./sidebar.js";

document.addEventListener("DOMContentLoaded", () => {
	document.addEventListener("keydown", (event) => {
		if (event.key !== "Escape") return;
		const sidebar = document.getElementById("mainSidebar");
		if (sidebar?.classList.contains("open")) toggleSidebar();
	});
});
