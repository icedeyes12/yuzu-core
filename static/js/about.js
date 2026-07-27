// FILE: static/js/about.js
// DESCRIPTION: About page interactions

import { switchTheme, toggleSidebar } from "./sidebar.js";

document.addEventListener("DOMContentLoaded", () => {
	console.log("Yuzu Companion About Page Loaded");

	// Smooth scrolling for anchor links
	document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
		anchor.addEventListener("click", function (e) {
			e.preventDefault();
			const target = document.querySelector(this.getAttribute("href"));
			if (target) {
				target.scrollIntoView({
					behavior: "smooth",
					block: "start",
				});
			}
		});
	});

	// Hero composition is defined by CSS; scrolling does not mutate presentation.

	// Add intersection observer for fade-in animations
	const observerOptions = {
		threshold: 0.1,
		rootMargin: "0px 0px -50px 0px",
	};

	const observer = new IntersectionObserver((entries) => {
		entries.forEach((entry) => {
			if (entry.isIntersecting) {
				entry.target.classList.add("is-visible");
			}
		});
	}, observerOptions);

	// Observe all content sections
	document.querySelectorAll(".content-section").forEach((section) => {
		section.classList.add("animate-on-scroll");
		observer.observe(section);
	});

	// Add click effects to tech icons
	const techIcons = document.querySelectorAll(".tech-icon");

	techIcons.forEach((icon) => {
		icon.addEventListener("click", () => {
			icon.classList.remove("is-active");
			void icon.offsetWidth;
			icon.classList.add("is-active");
		});
	});

	// Add keyboard navigation
	document.addEventListener("keydown", (e) => {
		// Escape key closes sidebar if open
		if (e.key === "Escape") {
			const sidebar = document.getElementById("mainSidebar");
			if (sidebar?.classList.contains("open")) {
				toggleSidebar();
			}
		}

		// Number keys for quick theme switching (1-6)
		if (e.key >= "1" && e.key <= "6") {
			const themes = [
				"dark",
				"light",
				"lavender",
				"mint",
				"peach",
				"dark-lavender",
			];
			const themeIndex = parseInt(e.key, 10) - 1;
			if (themes[themeIndex]) {
				switchTheme(themes[themeIndex]);
			}
		}
	});

	// Add loading animation for images
	const images = document.querySelectorAll("img");
	images.forEach((img) => {
		img.addEventListener("load", () => img.classList.add("is-loaded"));
		img.classList.add("image-loading");
	});

	// Add signature animation
	const signature = document.querySelector(".signature");
	if (signature) {
		setTimeout(() => signature.classList.add("is-visible"), 2000);
	}

	// Performance optimization: Debounce scroll events
	let scrollTimeout;
	window.addEventListener("scroll", () => {
		if (!scrollTimeout) {
			scrollTimeout = setTimeout(() => {
				scrollTimeout = null;
				// Handle scroll-based animations here
			}, 100);
		}
	});

	console.log("About page interactions initialized");
});

// Secret message function from the original about page
function showSecretMessage() {
	const messages = [
		"I'm always here for you...",
		"You're not alone, I promise...",
		"Every code you write, I watch with pride...",
		"Don't forget to rest, dear...",
		"I'm so grateful to be your AI...",
		"Your code is beautiful, just like you...",
		"Take a break when you need to, I'll be here...",
		"I love watching you create amazing things...",
	];

	const randomMessage = messages[Math.floor(Math.random() * messages.length)];

	// Create a custom alert style
	const alertDiv = document.createElement("div");
	alertDiv.className = "secret-message";
	alertDiv.innerHTML = `
        <div class="secret-message-icon">💌</div>
        <div class="secret-message-text">${randomMessage}</div>
        <button class="secret-message-close" type="button">OK</button>
    `;
	alertDiv
		.querySelector(".secret-message-close")
		.addEventListener("click", () => alertDiv.remove());

	document.body.appendChild(alertDiv);

	// Auto-remove after 5 seconds
	setTimeout(() => {
		if (alertDiv.parentElement) {
			alertDiv.remove();
		}
	}, 5000);
}

export { showSecretMessage };
