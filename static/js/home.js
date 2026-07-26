// FILE: static/js/home.js
// DESCRIPTION: Home page functionality
document.addEventListener("DOMContentLoaded", () => {
	console.log("Home page loaded - initializing...");
	initializeHomePage();
	loadRecentSessions();
	initializeHomeAnimations();
});

function initializeHomePage() {
	console.log("Setting up home page interactions...");

	// Add click effects to cards
	const cards = document.querySelectorAll(".card");

	cards.forEach((card) => {
		// Add ripple effect
		card.addEventListener("click", function (e) {
			createRippleEffect(e, this);
		});

		// Add keyboard navigation
		card.addEventListener("keydown", function (e) {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				this.click();
			}
		});

		// Make cards focusable
		card.setAttribute("tabindex", "0");
	});

	// Add keyboard shortcuts
	document.addEventListener("keydown", (e) => {
		// Number keys for quick navigation
		if (e.key === "1") {
			window.location.href = "/chat";
		} else if (e.key === "2") {
			window.location.href = "/config";
		}

		// Escape to close sidebar
		if (e.key === "Escape") {
			const sidebar = document.getElementById("mainSidebar");
			if (sidebar?.classList.contains("open")) {
				window.toggleSidebar();
			}
		}
	});

	// Add footer interaction
	const footerLink = document.querySelector(".footer-link");
	if (footerLink) {
		footerLink.addEventListener("click", function () {
			// Add click animation
			this.classList.add("footer-click");
		});
	}

	console.log("Home page interactions initialized");
}

async function loadRecentSessions() {
	try {
		const response = await fetch("/api/profile");
		const data = await response.json();

		const sessionsContainer = document.getElementById("recent-sessions");
		if (!sessionsContainer) return;

		const recentSessions = data.chat_history
			.filter((msg) => msg.role === "system")
			.slice(-5)
			.reverse();

		if (recentSessions.length === 0) {
			sessionsContainer.innerHTML = `
                <div class="no-sessions">
                    <p>No recent sessions found.</p>
                    <p class="hint">Start chatting to see your session history here!</p>
                </div>
            `;
			return;
		}

		sessionsContainer.innerHTML = recentSessions
			.map(
				(session) => `
            <div class="session-item">
                <p><strong>${session.content.replace(/\*/g, "")}</strong></p>
                <small>${new Date(session.timestamp).toLocaleString()}</small>
            </div>
        `,
			)
			.join("");

		// Add animations to session items
		setTimeout(() => {
			document.querySelectorAll(".session-item").forEach((item, index) => {
				item.style.setProperty("--animation-delay", `${index * 0.1}s`);
				item.classList.add("fade-in-up");
			});
		}, 100);

		console.log(`Loaded ${recentSessions.length} recent sessions`);
	} catch (error) {
		console.error("Error loading sessions:", error);
		const sessionsContainer = document.getElementById("recent-sessions");
		if (sessionsContainer) {
			sessionsContainer.innerHTML = `
                <div class="error-state">
                    <p>Error loading sessions.</p>
                    <button onclick="loadRecentSessions()" class="retry-btn">Retry</button>
                </div>
            `;
		}
	}
}

function initializeHomeAnimations() {
	console.log("Initializing home page animations...");

	// Add intersection observer for cards
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

	// Observe all cards
	document.querySelectorAll(".card").forEach((card, index) => {
		card.classList.add("animate-on-scroll");
		card.style.setProperty("--animation-delay", `${index * 0.1}s`);
		observer.observe(card);
	});

	// Add header animation
	const header = document.querySelector(".home-header");
	if (header) {
		header.classList.add("animate-on-load");
		setTimeout(() => {
			header.classList.add("is-visible");
		}, 300);
	}

	// Add background pattern animation
	createBackgroundPattern();

	console.log("Home animations initialized");
}

function createRippleEffect(event, element) {
	const ripple = document.createElement("span");
	const rect = element.getBoundingClientRect();
	const size = Math.max(rect.width, rect.height);
	const x = event.clientX - rect.left - size / 2;
	const y = event.clientY - rect.top - size / 2;

	ripple.className = "card-ripple";
	ripple.style.setProperty("--ripple-size", `${size}px`);
	ripple.style.setProperty("--ripple-x", `${x}px`);
	ripple.style.setProperty("--ripple-y", `${y}px`);
	element.classList.add("ripple-container");
	element.appendChild(ripple);

	setTimeout(() => {
		ripple.remove();
	}, 600);
}

function createBackgroundPattern() {
	document.body.classList.add("home-body");
}

// Performance optimization: Debounce resize events
let resizeTimeout;
window.addEventListener("resize", () => {
	if (!resizeTimeout) {
		resizeTimeout = setTimeout(() => {
			resizeTimeout = null;
			// Handle responsive adjustments here
		}, 250);
	}
});

// Export functions for global access
window.loadRecentSessions = loadRecentSessions;
window.toggleSidebar = window.toggleSidebar || (() => {});
