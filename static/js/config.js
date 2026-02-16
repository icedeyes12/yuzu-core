// [FILE: config.js]
// [VERSION: 1.0.0.69.1]
// [DATE: 2025-08-12]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: Configuration page functionality]
// [AUTHOR: Project Lead: Bani Baskara]
// [TEAM: Deepseek, GPT, Qwen, Aihara]
// [REPOSITORY: https://github.com/icedeyes12]
// [LICENSE: MIT]

// Configuration page functionality
document.addEventListener('DOMContentLoaded', function() {
    console.log('Config page loaded - initializing...');
    loadProfileData();
    loadAPIKeys();
    loadGlobalKnowledge();
    loadProviderSettings();
    setupEventListeners();
    initializeConfigAnimations();
});

// Load profile data with proper global profile display
async function loadProfileData() {
    try {
        const response = await fetch('/api/get_profile');
        const data = await response.json();
        
        console.log('Full profile data:', data);

        // Update GLOBAL PLAYER PROFILE display
        const profileMemory = data.memory || {};
        console.log('Profile memory data:', profileMemory);
        
        const keyFacts = profileMemory.key_facts || {};
        console.log('Key facts data:', keyFacts);
        
        // Update the display with actual data
        document.getElementById('player-summary').textContent = 
            profileMemory.player_summary || 'No global profile yet. Click "Update Global Profile" to analyze all sessions!';
        
        document.getElementById('player-likes').textContent = 
            Array.isArray(keyFacts.likes) && keyFacts.likes.length > 0 ? 
            keyFacts.likes.join(', ') : 'None yet';
            
        document.getElementById('player-dislikes').textContent = 
            Array.isArray(keyFacts.dislikes) && keyFacts.dislikes.length > 0 ? 
            keyFacts.dislikes.join(', ') : 'None yet';
            
        document.getElementById('player-personality').textContent = 
            Array.isArray(keyFacts.personality_traits) && keyFacts.personality_traits.length > 0 ? 
            keyFacts.personality_traits.join(', ') : 'None yet';
            
        document.getElementById('player-memories').textContent = 
            Array.isArray(keyFacts.important_memories) && keyFacts.important_memories.length > 0 ? 
            keyFacts.important_memories.join(', ') : 'None yet';
            
        document.getElementById('player-relationship').textContent = 
            profileMemory.relationship_dynamics || 'No relationship dynamics yet';
            
        document.getElementById('global-profile-last-updated').textContent = 
            profileMemory.last_global_summary || 'Never';
        
        // Update affection display
        document.getElementById('affection-value').textContent = data.affection;
        document.getElementById('affection-level').value = data.affection;
        
        // Update form fields
        document.getElementById('display-name').value = data.display_name || '';
        document.getElementById('partner-name').value = data.partner_name || '';
        
        console.log('Profile data loaded successfully');
        
        // Load structured memory stats
        loadMemoryStats();
        
    } catch (error) {
        console.error('Error loading profile data:', error);
        document.getElementById('player-summary').textContent = 'Error loading global profile';
        showError('Failed to load profile data');
    }
}

// Load provider settings
async function loadProviderSettings() {
    try {
        const response = await fetch('/api/providers/list');
        const data = await response.json();
        
        if (data.status === 'success') {
            // Populate provider dropdown
            const providerSelect = document.getElementById('ai-provider');
            providerSelect.innerHTML = '';
            
            data.available_providers.forEach(provider => {
                const option = document.createElement('option');
                option.value = provider;
                option.textContent = provider.charAt(0).toUpperCase() + provider.slice(1);
                if (provider === data.current_provider) {
                    option.selected = true;
                }
                providerSelect.appendChild(option);
            });
            
            // Update current provider display
            document.getElementById('current-provider').textContent = 
                `${data.current_provider}/${data.current_model}`;
            
            // Populate models based on current provider
            updateModelDropdown(data.current_provider, data.all_models, data.current_model);
            
            // Test connection for current provider
            testProviderConnection(data.current_provider);
            
            console.log('Provider settings loaded');
        }
    } catch (error) {
        console.error('Error loading provider settings:', error);
        document.getElementById('current-provider').textContent = 'Error loading';
        document.getElementById('connection-status').textContent = 'Error';
        document.getElementById('connection-status').className = 'status-disconnected';
        showError('Failed to load provider settings');
    }
}

// Update model dropdown based on selected provider
function updateModelDropdown(provider, allModels, currentModel = '') {
    const modelSelect = document.getElementById('ai-model');
    modelSelect.innerHTML = '';
    
    const models = allModels[provider] || [];
    
    if (models.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No models available';
        modelSelect.appendChild(option);
        return;
    }
    
    models.forEach(model => {
        const option = document.createElement('option');
        option.value = model;
        option.textContent = model;
        if (model === currentModel) {
            option.selected = true;
        }
        modelSelect.appendChild(option);
    });
    
    console.log(`Updated model dropdown for ${provider}`);
}

// Test provider connection
async function testProviderConnection(providerName) {
    const statusElement = document.getElementById('connection-status');
    statusElement.textContent = 'Testing...';
    statusElement.className = 'status-checking';
    
    // Add loading animation
    statusElement.classList.add('pulse');
    
    try {
        const response = await fetch('/api/providers/test_connection', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ provider_name: providerName })
        });
        
        const result = await response.json();
        
        // Remove loading animation
        statusElement.classList.remove('pulse');
        
        if (result.status === 'success') {
            statusElement.textContent = result.connected ? 'Connected' : 'Connection failed';
            statusElement.className = result.connected ? 'status-connected' : 'status-disconnected';
            
            if (result.connected) {
                showSuccess(`${providerName} connection successful!`);
            } else {
                showError(`${providerName} connection failed`);
            }
        } else {
            statusElement.textContent = 'Test failed';
            statusElement.className = 'status-disconnected';
            showError('Provider test failed');
        }
    } catch (error) {
        console.error('Error testing provider connection:', error);
        statusElement.classList.remove('pulse');
        statusElement.textContent = 'Test error';
        statusElement.className = 'status-disconnected';
        showError('Error testing provider connection');
    }
}

function setupEventListeners() {
    console.log('Setting up config event listeners...');
    
    // Profile settings
    const saveProfileBtn = document.getElementById('save-profile');
    const affectionSlider = document.getElementById('affection-level');
    const affectionValue = document.getElementById('affection-value');
    
    if (saveProfileBtn) {
        saveProfileBtn.addEventListener('click', saveProfileSettings);
    }
    
    if (affectionSlider) {
        affectionSlider.addEventListener('input', function() {
            affectionValue.textContent = this.value;
            // Add visual feedback
            this.style.setProperty('--slider-progress', `${this.value}%`);
        });
        
        // Initialize slider progress
        affectionSlider.style.setProperty('--slider-progress', `${affectionSlider.value}%`);
    }
    
    // API key management
    const addApiKeyBtn = document.getElementById('add-api-key');
    if (addApiKeyBtn) {
        addApiKeyBtn.addEventListener('click', addAPIKey);
    }
    
    // Memory and data
    const rebuildMemoryBtn = document.getElementById('rebuild-memory');
    const runDecayBtn = document.getElementById('run-decay');
    const updateGlobalProfileBtn = document.getElementById('update-global-profile');
    const clearChatHistoryBtn = document.getElementById('clear-chat-history');
    
    if (rebuildMemoryBtn) {
        rebuildMemoryBtn.addEventListener('click', rebuildStructuredMemory);
    }
    
    if (runDecayBtn) {
        runDecayBtn.addEventListener('click', runMemoryDecay);
    }
    
    if (updateGlobalProfileBtn) {
        updateGlobalProfileBtn.addEventListener('click', updateGlobalProfile);
    }
    
    if (clearChatHistoryBtn) {
        clearChatHistoryBtn.addEventListener('click', clearChatHistory);
    }
    
    // Global knowledge
    const saveGlobalKnowledgeBtn = document.getElementById('save-global-knowledge');
    if (saveGlobalKnowledgeBtn) {
        saveGlobalKnowledgeBtn.addEventListener('click', saveGlobalKnowledge);
    }
    
    // Provider settings
    const providerSelect = document.getElementById('ai-provider');
    const testProviderBtn = document.getElementById('test-provider');
    const saveProviderBtn = document.getElementById('save-provider');
    
    if (providerSelect) {
        providerSelect.addEventListener('change', function() {
            const selectedProvider = this.value;
            if (selectedProvider) {
                fetch('/api/providers/list')
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            updateModelDropdown(selectedProvider, data.all_models);
                            testProviderConnection(selectedProvider);
                        }
                    })
                    .catch(error => {
                        console.error('Error loading provider models:', error);
                        showError('Failed to load provider models');
                    });
            }
        });
    }
    
    if (testProviderBtn) {
        testProviderBtn.addEventListener('click', function() {
            const selectedProvider = providerSelect.value;
            if (selectedProvider) {
                testProviderConnection(selectedProvider);
            } else {
                showError('Please select a provider first');
            }
        });
    }
    
    if (saveProviderBtn) {
        saveProviderBtn.addEventListener('click', saveProviderSettings);
    }
    
    // Add keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Ctrl+S to save profile (except when in textarea)
        if ((e.ctrlKey || e.metaKey) && e.key === 's' && e.target.tagName !== 'TEXTAREA') {
            e.preventDefault();
            saveProfileSettings();
        }
        
        // Escape to close sidebar
        if (e.key === 'Escape') {
            const sidebar = document.getElementById('mainSidebar');
            if (sidebar && sidebar.classList.contains('open')) {
                toggleSidebar();
            }
        }
    });
    
    console.log('Event listeners setup complete');
}

// Save provider settings
async function saveProviderSettings() {
    const providerSelect = document.getElementById('ai-provider');
    const modelSelect = document.getElementById('ai-model');
    
    const providerName = providerSelect.value;
    const modelName = modelSelect.value;
    
    if (!providerName) {
        showError('Please select an AI provider');
        return;
    }
    
    if (!modelName) {
        showError('Please select a model');
        return;
    }
    
    // Show loading state
    const saveBtn = document.getElementById('save-provider');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;
    
    try {
        const response = await fetch('/api/providers/set_preferred', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                provider_name: providerName,
                model_name: modelName
            })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showSuccess('AI provider settings saved!');
            // Update display
            document.getElementById('current-provider').textContent = `${providerName}/${modelName}`;
            // Test the new connection
            testProviderConnection(providerName);
        } else {
            showError('Failed to save provider settings: ' + result.message);
        }
    } catch (error) {
        console.error('Error saving provider settings:', error);
        showError('Error saving provider settings');
    } finally {
        // Restore button state
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

async function saveProfileSettings() {
    const displayName = document.getElementById('display-name').value;
    const partnerName = document.getElementById('partner-name').value;
    const affection = document.getElementById('affection-level').value;
    
    // Validate inputs
    if (!displayName.trim()) {
        showError('Display name is required');
        return;
    }
    
    if (!partnerName.trim()) {
        showError('Partner name is required');
        return;
    }
    
    // Show loading state
    const saveBtn = document.getElementById('save-profile');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;
    
    try {
        const response = await fetch('/api/update_profile', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                display_name: displayName,
                partner_name: partnerName,
                affection: parseInt(affection)
            })
        });
        
        if (response.ok) {
            showSuccess('Profile settings saved successfully!');
            loadProfileData(); // Reload to reflect changes
        } else {
            showError('Error saving profile settings');
        }
    } catch (error) {
        console.error('Error saving profile:', error);
        showError('Error saving profile settings');
    } finally {
        // Restore button state
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

async function loadAPIKeys() {
    try {
        const response = await fetch('/api/get_profile');
        const data = await response.json();
        
        const keysList = document.getElementById('keys-list');
        
        if (!data.api_keys || Object.keys(data.api_keys).length === 0) {
            keysList.innerHTML = '<li>No API keys stored</li>';
            return;
        }
        
        keysList.innerHTML = Object.entries(data.api_keys).map(([keyName, keyValue]) => `
            <li style="margin-bottom: 0.5rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 5px; display: flex; justify-content: space-between; align-items: center;">
                <span><strong>${keyName}:</strong> ${keyValue.substring(0, 10)}...${keyValue.substring(keyValue.length - 5)}</span>
                <button onclick="removeAPIKey('${keyName}')" class="btn" style="background: #ef4444; color: white; padding: 0.3rem 0.6rem; font-size: 0.8rem;">Remove</button>
            </li>
        `).join('');
        
        console.log('API keys loaded');
        
    } catch (error) {
        console.error('Error loading API keys:', error);
        document.getElementById('keys-list').innerHTML = '<li>Error loading API keys</li>';
        showError('Failed to load API keys');
    }
}

async function addAPIKey() {
    const providerSelect = document.getElementById('api-key-provider');
    const apiKeyInput = document.getElementById('api-key');
    
    const keyName = providerSelect.value;
    const apiKey = apiKeyInput.value.trim();
    
    if (!apiKey) {
        showError('Please enter an API key');
        return;
    }
    
    // Show loading state
    const addBtn = document.getElementById('add-api-key');
    const originalText = addBtn.textContent;
    addBtn.textContent = 'Adding...';
    addBtn.disabled = true;
    
    try {
        const response = await fetch('/api/add_api_key', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                key_name: keyName,
                api_key: apiKey 
            })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showSuccess('API key added successfully!');
            apiKeyInput.value = '';
            loadAPIKeys(); // Reload the list
            // Reload provider settings to reflect new key availability
            loadProviderSettings();
        } else {
            showError('Failed to add API key: ' + result.message);
        }
    } catch (error) {
        console.error('Error adding API key:', error);
        showError('Error adding API key');
    } finally {
        // Restore button state
        addBtn.textContent = originalText;
        addBtn.disabled = false;
    }
}

async function removeAPIKey(keyName) {
    if (!confirm(`Are you sure you want to remove the ${keyName} API key?`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/remove_api_key', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ key_name: keyName })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showSuccess('API key removed!');
            loadAPIKeys(); // Reload the list
            // Reload provider settings to reflect key removal
            loadProviderSettings();
        } else {
            showError('Failed to remove API key: ' + result.message);
        }
    } catch (error) {
        console.error('Error removing API key:', error);
        showError('Error removing API key');
    }
}

// Load structured memory statistics
async function loadMemoryStats() {
    try {
        const response = await fetch('/api/memory_stats');
        const data = await response.json();

        if (data.status === 'success') {
            const stats = data.stats;
            document.getElementById('semantic-count').textContent = stats.semantic || 0;
            document.getElementById('episodic-count').textContent = stats.episodic || 0;
            document.getElementById('segment-count').textContent = stats.segments || 0;

            const factsList = document.getElementById('top-facts-list');
            if (stats.top_facts && stats.top_facts.length > 0) {
                factsList.innerHTML = stats.top_facts.map(f => `<li>${f}</li>`).join('');
            } else {
                factsList.innerHTML = '<li>No facts extracted yet. Start chatting or click "Rebuild Structured Memory".</li>';
            }
        }
    } catch (error) {
        console.error('Error loading memory stats:', error);
    }
}

async function rebuildStructuredMemory() {
    if (!confirm('Rebuild structured memory? This will re-extract facts and segments from the last 50 messages in the current session.')) {
        return;
    }

    const btn = document.getElementById('rebuild-memory');
    const originalText = btn.textContent;
    btn.textContent = 'Rebuilding...';
    btn.disabled = true;

    try {
        const response = await fetch('/api/rebuild_structured_memory', {
            method: 'POST'
        });

        const result = await response.json();

        if (result.status === 'success') {
            showSuccess(result.message);
            loadMemoryStats();
        } else {
            showError('Failed to rebuild memory: ' + (result.message || result.error));
        }
    } catch (error) {
        console.error('Error rebuilding structured memory:', error);
        showError('Error rebuilding structured memory');
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

async function runMemoryDecay() {
    if (!confirm('Run memory decay? This applies FSRS-style forgetting: old unused memories will fade, frequently used ones will be preserved.')) {
        return;
    }

    const btn = document.getElementById('run-decay');
    const originalText = btn.textContent;
    btn.textContent = 'Running...';
    btn.disabled = true;

    try {
        const response = await fetch('/api/run_memory_decay', {
            method: 'POST'
        });

        const result = await response.json();

        if (result.status === 'success') {
            showSuccess(result.message);
            loadMemoryStats();
        } else {
            showError('Failed to run decay: ' + (result.message || result.error));
        }
    } catch (error) {
        console.error('Error running memory decay:', error);
        showError('Error running memory decay');
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

async function updateGlobalProfile() {
    if (!confirm('Update global player profile? This will analyze ALL sessions to build a comprehensive profile. This may take a moment.')) {
        return;
    }
    
    // Show loading state
    const updateBtn = document.getElementById('update-global-profile');
    const originalText = updateBtn.textContent;
    updateBtn.textContent = 'Analyzing...';
    updateBtn.disabled = true;
    
    try {
        const response = await fetch('/api/update_global_profile', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showSuccess('Global player profile updated from ALL sessions!');
            // Use the returned profile data directly
            if (result.profile && result.profile.memory) {
                updateGlobalProfileDisplay(result.profile.memory);
            } else {
                loadProfileData(); // Fallback to reload
            }
        } else {
            showError('Failed to update global profile: ' + result.message);
        }
    } catch (error) {
        console.error('Error updating global profile:', error);
        showError('Error updating global profile');
    } finally {
        // Restore button state
        updateBtn.textContent = originalText;
        updateBtn.disabled = false;
    }
}

// Direct update function for global profile display
function updateGlobalProfileDisplay(profileMemory) {
    console.log('Updating global profile display with:', profileMemory);
    
    const keyFacts = profileMemory.key_facts || {};
    
    document.getElementById('player-summary').textContent = 
        profileMemory.player_summary || 'Profile analysis completed but no summary generated.';
        
    document.getElementById('player-likes').textContent = 
        Array.isArray(keyFacts.likes) && keyFacts.likes.length > 0 ? 
        keyFacts.likes.join(', ') : 'None identified';
        
    document.getElementById('player-dislikes').textContent = 
        Array.isArray(keyFacts.dislikes) && keyFacts.dislikes.length > 0 ? 
        keyFacts.dislikes.join(', ') : 'None identified';
        
    document.getElementById('player-personality').textContent = 
        Array.isArray(keyFacts.personality_traits) && keyFacts.personality_traits.length > 0 ? 
        keyFacts.personality_traits.join(', ') : 'None identified';
        
    document.getElementById('player-memories').textContent = 
        Array.isArray(keyFacts.important_memories) && keyFacts.important_memories.length > 0 ? 
        keyFacts.important_memories.join(', ') : 'None identified';
        
    document.getElementById('player-relationship').textContent = 
        profileMemory.relationship_dynamics || 'No specific relationship dynamics identified';
        
    document.getElementById('global-profile-last-updated').textContent = 
        profileMemory.last_global_summary || 'Just now';
}

async function clearChatHistory() {
    if (!confirm('Are you sure you want to clear all chat history in the current session? This cannot be undone.')) {
        return;
    }
    
    // Show loading state
    const clearBtn = document.getElementById('clear-chat-history');
    const originalText = clearBtn.textContent;
    clearBtn.textContent = 'Clearing...';
    clearBtn.disabled = true;
    
    try {
        const response = await fetch('/api/clear_chat', { method: 'POST' });
        
        if (response.ok) {
            showSuccess('Chat history cleared successfully!');
            loadProfileData(); // Reload to reflect cleared history
        } else {
            showError('Error clearing chat history');
        }
    } catch (error) {
        console.error('Error clearing chat:', error);
        showError('Error clearing chat history');
    } finally {
        // Restore button state
        clearBtn.textContent = originalText;
        clearBtn.disabled = false;
    }
}

// Global knowledge functions
async function loadGlobalKnowledge() {
    try {
        const response = await fetch('/api/get_profile');
        const data = await response.json();
        
        const globalKnowledge = data.global_knowledge || {};
        document.getElementById('global-knowledge').value = globalKnowledge.facts || '';
        
        console.log('Global knowledge loaded');
    } catch (error) {
        console.error('Error loading global knowledge:', error);
        showError('Failed to load global knowledge');
    }
}

async function saveGlobalKnowledge() {
    const facts = document.getElementById('global-knowledge').value.trim();
    
    // Show loading state
    const saveBtn = document.getElementById('save-global-knowledge');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;
    
    try {
        const response = await fetch('/api/global_knowledge/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ facts: facts })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showSuccess('Global knowledge saved! This will be used in all sessions.');
        } else {
            showError('Error saving global knowledge');
        }
    } catch (error) {
        console.error('Error saving global knowledge:', error);
        showError('Error saving global knowledge');
    } finally {
        // Restore button state
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

// UI Helper Functions
function showSuccess(message) {
    showNotification(message, 'success');
}

function showError(message) {
    showNotification(message, 'error');
}

function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existingNotifications = document.querySelectorAll('.config-notification');
    existingNotifications.forEach(notification => notification.remove());
    
    const notification = document.createElement('div');
    notification.className = `config-notification ${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <span class="notification-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
            <span class="notification-message">${message}</span>
            <button class="notification-close" onclick="this.parentElement.parentElement.remove()">×</button>
        </div>
    `;
    
    // Add styles
    notification.style.cssText = `
        position: fixed;
        top: 100px;
        right: 20px;
        background: ${type === 'success' ? 'var(--accent-mint)' : type === 'error' ? 'var(--accent-pink)' : 'var(--accent-lavender)'};
        color: var(--button-text);
        padding: 1rem;
        border-radius: 8px;
        box-shadow: var(--shadow-soft);
        z-index: 10000;
        max-width: 300px;
        animation: slideInRight 0.3s ease;
    `;
    
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 5000);
}

// Initialize config animations
function initializeConfigAnimations() {
    // Add intersection observer for config sections
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

    // Observe all config sections
    document.querySelectorAll('.config-section').forEach(section => {
        section.style.opacity = '0';
        section.style.transform = 'translateY(20px)';
        section.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(section);
    });
    
    console.log('Config animations initialized');
}

// Make functions globally available
window.removeAPIKey = removeAPIKey;
window.showSuccess = showSuccess;
window.showError = showError;