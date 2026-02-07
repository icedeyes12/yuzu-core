// [FILE: home.js]
// [VERSION: 1.0.0.69.1]
// [DATE: 2025-08-12]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: Home page functionality]
// [AUTHOR: Project Lead: Bani Baskara]
// [TEAM: Deepseek, GPT, Qwen, Aihara]
// [REPOSITORY: https://github.com/icedeyes12]
// [LICENSE: MIT]

// Home page functionality
document.addEventListener('DOMContentLoaded', function() {
    console.log('Home page loaded - initializing...');
    initializeHomePage();
    loadRecentSessions();
    initializeHomeAnimations();
});

function initializeHomePage() {
    console.log('Setting up home page interactions...');
    
    // Add click effects to cards
    const cards = document.querySelectorAll('.card');
    
    cards.forEach(card => {
        // Add ripple effect
        card.addEventListener('click', function(e) {
            createRippleEffect(e, this);
        });
        
        // Add keyboard navigation
        card.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
        
        // Make cards focusable
        card.setAttribute('tabindex', '0');
    });
    
    // Add keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Number keys for quick navigation
        if (e.key === '1') {
            window.location.href = '/chat';
        } else if (e.key === '2') {
            window.location.href = '/config';
        }
        
        // Escape to close sidebar
        if (e.key === 'Escape') {
            const sidebar = document.getElementById('mainSidebar');
            if (sidebar && sidebar.classList.contains('open')) {
                toggleSidebar();
            }
        }
    });
    
    // Add footer interaction
    const footerLink = document.querySelector('.footer-link');
    if (footerLink) {
        footerLink.addEventListener('click', function() {
            // Add click animation
            this.style.transform = 'scale(0.95)';
            setTimeout(() => {
                this.style.transform = 'scale(1)';
            }, 150);
        });
    }
    
    console.log('Home page interactions initialized');
}

async function loadRecentSessions() {
    try {
        const response = await fetch('/api/get_profile');
        const data = await response.json();
        
        const sessionsContainer = document.getElementById('recent-sessions');
        if (!sessionsContainer) return;
        
        const recentSessions = data.chat_history
            .filter(msg => msg.role === 'system')
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
        
        sessionsContainer.innerHTML = recentSessions.map(session => `
            <div class="session-item">
                <p><strong>${session.content.replace(/\*/g, '')}</strong></p>
                <small>${new Date(session.timestamp).toLocaleString()}</small>
            </div>
        `).join('');
        
        // Add animations to session items
        setTimeout(() => {
            document.querySelectorAll('.session-item').forEach((item, index) => {
                item.style.animationDelay = `${index * 0.1}s`;
                item.classList.add('fade-in-up');
            });
        }, 100);
        
        console.log(`Loaded ${recentSessions.length} recent sessions`);
        
    } catch (error) {
        console.error('Error loading sessions:', error);
        const sessionsContainer = document.getElementById('recent-sessions');
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
    console.log('Initializing home page animations...');
    
    // Add intersection observer for cards
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

    // Observe all cards
    document.querySelectorAll('.card').forEach((card, index) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(30px)';
        card.style.transition = `opacity 0.6s ease ${index * 0.1}s, transform 0.6s ease ${index * 0.1}s`;
        observer.observe(card);
    });
    
    // Add header animation
    const header = document.querySelector('.home-header');
    if (header) {
        header.style.opacity = '0';
        header.style.transform = 'translateY(-20px)';
        header.style.transition = 'opacity 0.8s ease, transform 0.8s ease';
        
        setTimeout(() => {
            header.style.opacity = '1';
            header.style.transform = 'translateY(0)';
        }, 300);
    }
    
    // Add background pattern animation
    createBackgroundPattern();
    
    console.log('Home animations initialized');
}

function createRippleEffect(event, element) {
    const ripple = document.createElement('span');
    const rect = element.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = event.clientX - rect.left - size / 2;
    const y = event.clientY - rect.top - size / 2;
    
    ripple.style.cssText = `
        position: absolute;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.3);
        transform: scale(0);
        animation: ripple-animation 0.6s linear;
        width: ${size}px;
        height: ${size}px;
        left: ${x}px;
        top: ${y}px;
        pointer-events: none;
    `;
    
    element.style.position = 'relative';
    element.style.overflow = 'hidden';
    element.appendChild(ripple);
    
    setTimeout(() => {
        ripple.remove();
    }, 600);
}

function createBackgroundPattern() {
    // Create a subtle animated background
    const style = document.createElement('style');
    style.textContent = `
        @keyframes float {
            0%, 100% { transform: translateY(0px) rotate(0deg); }
            50% { transform: translateY(-20px) rotate(180deg); }
        }
        
        .home-body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 20% 80%, rgba(168, 200, 255, 0.1) 0%, transparent 50%),
                radial-gradient(circle at 80% 20%, rgba(255, 184, 198, 0.1) 0%, transparent 50%),
                radial-gradient(circle at 40% 40%, rgba(184, 225, 221, 0.05) 0%, transparent 50%);
            animation: float 20s ease-in-out infinite;
            pointer-events: none;
            z-index: -1;
        }
        
        @keyframes ripple-animation {
            to {
                transform: scale(4);
                opacity: 0;
            }
        }
        
        .fade-in-up {
            animation: fadeInUp 0.6s ease forwards;
        }
        
        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .no-sessions, .error-state {
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
        }
        
        .hint {
            font-size: 0.9rem;
            opacity: 0.7;
            margin-top: 0.5rem;
        }
        
        .retry-btn {
            background: var(--button-bg);
            color: var(--button-text);
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            margin-top: 1rem;
            font-weight: 600;
        }
        
        .retry-btn:hover {
            transform: translateY(-1px);
        }
    `;
    
    document.head.appendChild(style);
}

// Performance optimization: Debounce resize events
let resizeTimeout;
window.addEventListener('resize', function() {
    if (!resizeTimeout) {
        resizeTimeout = setTimeout(function() {
            resizeTimeout = null;
            // Handle responsive adjustments here
        }, 250);
    }
});

// Export functions for global access
window.loadRecentSessions = loadRecentSessions;