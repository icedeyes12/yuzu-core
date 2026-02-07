// [FILE: sidebar.js]
// [VERSION: 1.0.0.69.3]
// [DATE: 2025-08-12]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: Unified sidebar management functionality with session actions - Markdown Safe]
// [AUTHOR: Project Lead: Bani Baskara]
// [TEAM: Deepseek, GPT, Qwen, Aihara]
// [REPOSITORY: https://github.com/icedeyes12]
// [LICENSE: MIT]

// Unified Sidebar Management
let currentTheme = 'dark';

function toggleSidebar() {
    const sidebar = document.getElementById('mainSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const hamburger = document.getElementById('hamburgerMenu');
    
    if (sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        hamburger.classList.remove('active');
    } else {
        sidebar.classList.add('open');
        overlay.classList.add('active');
        hamburger.classList.add('active');
        
        // Load sessions if on chat page
        if (window.location.pathname === '/chat') {
            loadSidebarSessions();
        }
    }
}

// Custom dropdown functionality
function initCustomDropdown() {
    const dropdown = document.getElementById('themeDropdown');
    if (!dropdown) return;
    
    const selected = dropdown.querySelector('.dropdown-selected');
    const options = dropdown.querySelector('.dropdown-options');
    const optionItems = dropdown.querySelectorAll('.dropdown-option');
    
    // Toggle dropdown
    selected.addEventListener('click', function(e) {
        e.stopPropagation();
        const isActive = options.classList.contains('active');
        
        // Close all other dropdowns
        document.querySelectorAll('.dropdown-options.active').forEach(opt => {
            if (opt !== options) opt.classList.remove('active');
        });
        document.querySelectorAll('.dropdown-selected.active').forEach(sel => {
            if (sel !== selected) sel.classList.remove('active');
        });
        
        // Toggle this dropdown
        options.classList.toggle('active', !isActive);
        selected.classList.toggle('active', !isActive);
    });
    
    // Handle option selection
    optionItems.forEach(option => {
        option.addEventListener('click', function() {
            const value = this.getAttribute('data-value');
            const text = this.textContent.trim();
            
            // Update selected display
            selected.querySelector('.selected-text').textContent = text;
            
            // Update active states
            optionItems.forEach(opt => opt.classList.remove('active'));
            this.classList.add('active');
            
            // Close dropdown
            options.classList.remove('active');
            selected.classList.remove('active');
            
            // Switch theme
            switchTheme(value);
        });
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', function() {
        options.classList.remove('active');
        selected.classList.remove('active');
    });
}

// Theme switching function
function switchTheme(theme) {
    currentTheme = theme;
    
    // Apply theme to body
    document.body.setAttribute('data-theme', theme);
    
    // Update custom dropdown display
    const dropdown = document.getElementById('themeDropdown');
    if (dropdown) {
        const option = dropdown.querySelector(`[data-value="${theme}"]`);
        if (option) {
            const text = option.textContent.trim();
            dropdown.querySelector('.selected-text').textContent = text;
            
            // Update active states
            dropdown.querySelectorAll('.dropdown-option').forEach(opt => {
                opt.classList.remove('active');
            });
            option.classList.add('active');
        }
    }
    
    // Save preference
    localStorage.setItem('yuzu-theme', theme);
    
    console.log(`Switched to ${theme} theme`);
}

// Enhanced session loading with action buttons - MARKDOWN SAFE
function loadSidebarSessions() {
    const sessionSection = document.getElementById('sessionSection');
    const sessionsList = document.getElementById('sidebarSessionsList');
    
    if (!sessionSection || !sessionsList) return;
    
    sessionSection.style.display = 'block';
    
    fetch('/api/sessions/list')
        .then(response => response.json())
        .then(data => {
            if (data.sessions && data.sessions.length > 0) {
                // Clear existing content safely
                sessionsList.innerHTML = '';
                
                data.sessions.forEach(session => {
                    const sessionItem = document.createElement('div');
                    sessionItem.className = `sidebar-session-item ${session.is_active ? 'active' : ''}`;
                    
                    // Create session content
                    const sessionContent = document.createElement('div');
                    sessionContent.className = 'session-content';
                    sessionContent.onclick = () => switchSession(session.id);
                    
                    const sessionName = document.createElement('div');
                    sessionName.className = 'sidebar-session-name';
                    sessionName.textContent = session.name;
                    
                    const sessionMeta = document.createElement('div');
                    sessionMeta.className = 'sidebar-session-meta';
                    sessionMeta.textContent = `${session.message_count || 0} messages • ${formatSessionDate(session.updated_at)}`;
                    
                    sessionContent.appendChild(sessionName);
                    sessionContent.appendChild(sessionMeta);
                    
                    // Create session actions
                    const sessionActions = document.createElement('div');
                    sessionActions.className = 'session-actions';
                    
                    // Rename button
                    const renameBtn = document.createElement('button');
                    renameBtn.className = 'session-action-btn rename-btn';
                    renameBtn.title = 'Rename session';
                    renameBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;
                    renameBtn.onclick = (e) => {
                        e.stopPropagation();
                        renameSessionPrompt(session.id, session.name);
                    };
                    
                    sessionActions.appendChild(renameBtn);
                    
                    // Delete button (only for non-active sessions)
                    if (!session.is_active) {
                        const deleteBtn = document.createElement('button');
                        deleteBtn.className = 'session-action-btn delete-btn';
                        deleteBtn.title = 'Delete session';
                        deleteBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`;
                        deleteBtn.onclick = (e) => {
                            e.stopPropagation();
                            deleteSessionPrompt(session.id);
                        };
                        sessionActions.appendChild(deleteBtn);
                    }
                    
                    // Assemble the item
                    sessionItem.appendChild(sessionContent);
                    sessionItem.appendChild(sessionActions);
                    sessionsList.appendChild(sessionItem);
                });
            } else {
                sessionsList.innerHTML = '<div class="no-sessions">No sessions yet</div>';
            }
        })
        .catch(error => {
            console.error('Error loading sidebar sessions:', error);
            sessionsList.innerHTML = '<div class="error">Failed to load sessions</div>';
        });
}

// Rename session functionality
function renameSessionPrompt(sessionId, currentName) {
    const newName = prompt('Enter new session name:', currentName);
    if (newName && newName.trim() && newName !== currentName) {
        renameSession(sessionId, newName.trim());
    }
}

function renameSession(sessionId, newName) {
    fetch('/api/sessions/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, name: newName })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // Reload sessions list
            loadSidebarSessions();
            
            // Update session name in header if this is the active session
            const sessionNameElement = document.getElementById('sessionName');
            if (sessionNameElement) {
                // Check if we're on the chat page and this is the active session
                fetch('/api/get_profile')
                    .then(response => response.json())
                    .then(profileData => {
                        if (profileData.active_session && profileData.active_session.id === sessionId) {
                            sessionNameElement.textContent = newName;
                        }
                    });
            }
            
            showNotification('Session renamed successfully!', 'success');
        } else {
            showNotification('Failed to rename session', 'error');
        }
    })
    .catch(error => {
        console.error('Error renaming session:', error);
        showNotification('Error renaming session', 'error');
    });
}

// Delete session functionality
function deleteSessionPrompt(sessionId) {
    if (confirm('Are you sure you want to delete this session? This action cannot be undone.')) {
        deleteSession(sessionId);
    }
}

function deleteSession(sessionId) {
    fetch('/api/sessions/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // Reload sessions list
            loadSidebarSessions();
            showNotification('Session deleted successfully!', 'success');
        } else {
            showNotification('Failed to delete session', 'error');
        }
    })
    .catch(error => {
        console.error('Error deleting session:', error);
        showNotification('Error deleting session', 'error');
    });
}

function createNewSession() {
    fetch('/api/sessions/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'New Chat' })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            loadSidebarSessions();
            toggleSidebar();
            
            // If on chat page, reload
            if (window.location.pathname === '/chat') {
                window.location.reload();
            } else {
                window.location.href = '/chat';
            }
        }
    })
    .catch(error => {
        console.error('Error creating session:', error);
        alert('Failed to create new session');
    });
}

function switchSession(sessionId) {
    fetch('/api/sessions/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            toggleSidebar();
            
            // Reload if on chat page
            if (window.location.pathname === '/chat') {
                window.location.reload();
            }
        }
    })
    .catch(error => {
        console.error('Error switching session:', error);
        alert('Failed to switch session');
    });
}

// Helper functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatSessionDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 1) {
        return 'Today';
    } else if (diffDays === 2) {
        return 'Yesterday';
    } else if (diffDays <= 7) {
        return `${diffDays - 1} days ago`;
    } else {
        return date.toLocaleDateString();
    }
}

// Notification system
function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existingNotification = document.querySelector('.session-notification');
    if (existingNotification) {
        existingNotification.remove();
    }
    
    const notification = document.createElement('div');
    notification.className = `session-notification ${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Auto-remove after 3 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 3000);
}

// Initialize theme on load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing sidebar...');
    
    // Get saved theme or default to dark
    const savedTheme = localStorage.getItem('yuzu-theme') || 'dark';
    console.log('Saved theme:', savedTheme);
    
    // Apply the theme immediately
    document.body.setAttribute('data-theme', savedTheme);
    currentTheme = savedTheme;
    
    // Initialize custom dropdown
    initCustomDropdown();
    
    // Set initial dropdown state
    const dropdown = document.getElementById('themeDropdown');
    if (dropdown) {
        const option = dropdown.querySelector(`[data-value="${savedTheme}"]`);
        if (option) {
            const text = option.textContent.trim();
            dropdown.querySelector('.selected-text').textContent = text;
            
            // Update active states
            dropdown.querySelectorAll('.dropdown-option').forEach(opt => {
                opt.classList.remove('active');
            });
            option.classList.add('active');
        }
    }
    
    console.log('Custom dropdown initialized');
    
    // Debug: Check if elements exist
    console.log('Sidebar elements check:');
    console.log('- mainSidebar:', document.getElementById('mainSidebar'));
    console.log('- themeDropdown:', document.getElementById('themeDropdown'));
    console.log('- hamburgerMenu:', document.getElementById('hamburgerMenu'));
});

// Make functions globally available
window.toggleSidebar = toggleSidebar;
window.switchTheme = switchTheme;
window.createNewSession = createNewSession;
window.switchSession = switchSession;
window.renameSessionPrompt = renameSessionPrompt;
window.renameSession = renameSession;
window.deleteSessionPrompt = deleteSessionPrompt;
window.deleteSession = deleteSession;
window.loadSidebarSessions = loadSidebarSessions;