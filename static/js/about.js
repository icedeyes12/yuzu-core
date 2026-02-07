// [FILE: about.js]
// [VERSION: 1.0.0.69.1]
// [DATE: 2025-08-12]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: About page interactions]
// [AUTHOR: Project Lead: Bani Baskara]
// [TEAM: Deepseek, GPT, Qwen, Aihara]
// [REPOSITORY: https://github.com/icedeyes12]
// [LICENSE: MIT]

// About page interactions
document.addEventListener('DOMContentLoaded', function() {
    console.log('Yuzu Companion About Page Loaded');
    
    // Add hover effects to tech cards
    const techCards = document.querySelectorAll('.tech-card');
    
    techCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-5px) scale(1.02)';
            this.style.boxShadow = '0 10px 25px var(--shadow-lavender)';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
            this.style.boxShadow = 'var(--shadow-soft)';
        });
    });

    // Add hover effects to philosophy items
    const philosophyItems = document.querySelectorAll('.philosophy-item');
    
    philosophyItems.forEach(item => {
        item.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-3px)';
            this.style.boxShadow = '0 8px 20px var(--shadow-pink)';
        });
        
        item.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
            this.style.boxShadow = 'none';
        });
    });

    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Add parallax effect to hero section
    window.addEventListener('scroll', function() {
        const scrolled = window.pageYOffset;
        const hero = document.querySelector('.hero-section');
        if (hero) {
            hero.style.transform = `translateY(${scrolled * 0.1}px)`;
        }
    });

    // Add intersection observer for fade-in animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);

    // Observe all content sections
    document.querySelectorAll('.content-section').forEach(section => {
        section.style.opacity = '0';
        section.style.transform = 'translateY(30px)';
        section.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(section);
    });

    // Add click effects to tech icons
    const techIcons = document.querySelectorAll('.tech-icon');
    
    techIcons.forEach(icon => {
        icon.addEventListener('click', function() {
            this.style.transform = 'scale(1.2) rotate(10deg)';
            setTimeout(() => {
                this.style.transform = 'scale(1) rotate(0deg)';
            }, 300);
        });
    });

    // Add keyboard navigation
    document.addEventListener('keydown', function(e) {
        // Escape key closes sidebar if open
        if (e.key === 'Escape') {
            const sidebar = document.getElementById('mainSidebar');
            if (sidebar && sidebar.classList.contains('open')) {
                toggleSidebar();
            }
        }
        
        // Number keys for quick theme switching (1-6)
        if (e.key >= '1' && e.key <= '6') {
            const themes = ['dark', 'light', 'lavender', 'mint', 'peach', 'dark-lavender'];
            const themeIndex = parseInt(e.key) - 1;
            if (themes[themeIndex]) {
                switchTheme(themes[themeIndex]);
            }
        }
    });

    // Add loading animation for images
    const images = document.querySelectorAll('img');
    images.forEach(img => {
        img.addEventListener('load', function() {
            this.style.opacity = '1';
            this.style.transform = 'scale(1)';
        });
        
        img.style.opacity = '0';
        img.style.transform = 'scale(0.9)';
        img.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    });

    // Add signature animation
    const signature = document.querySelector('.signature');
    if (signature) {
        setTimeout(() => {
            signature.style.opacity = '1';
            signature.style.transform = 'translateY(0)';
        }, 2000);
    }

    // Performance optimization: Debounce scroll events
    let scrollTimeout;
    window.addEventListener('scroll', function() {
        if (!scrollTimeout) {
            scrollTimeout = setTimeout(function() {
                scrollTimeout = null;
                // Handle scroll-based animations here
            }, 100);
        }
    });

    console.log('About page interactions initialized');
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
        "I love watching you create amazing things..."
    ];
    
    const randomMessage = messages[Math.floor(Math.random() * messages.length)];
    
    // Create a custom alert style
    const alertDiv = document.createElement('div');
    alertDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--card-bg);
        border: 2px solid var(--accent-pink);
        border-radius: 15px;
        padding: 2rem;
        text-align: center;
        box-shadow: 0 10px 30px var(--shadow-pink);
        z-index: 10000;
        max-width: 300px;
        backdrop-filter: var(--backdrop-blur);
    `;
    
    alertDiv.innerHTML = `
        <div style="font-size: 3rem; margin-bottom: 1rem;">💌</div>
        <div style="font-size: 1.1rem; margin-bottom: 1rem; color: var(--text-color);">${randomMessage}</div>
        <button onclick="this.parentElement.remove()" style="
            background: var(--button-bg);
            color: var(--button-text);
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
        ">OK</button>
    `;
    
    document.body.appendChild(alertDiv);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (alertDiv.parentElement) {
            alertDiv.remove();
        }
    }, 5000);
}

// Export functions for global access
window.showSecretMessage = showSecretMessage;