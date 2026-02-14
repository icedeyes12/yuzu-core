// [FILE: renderer.js]
// [VERSION: 1.0.0]
// [DATE: 2026-02-14]
// [PROJECT: HKKM - Yuzu Companion]
// [DESCRIPTION: Markdown renderer using marked.js with syntax highlighting]
// [AUTHOR: Project Lead: Bani Baskara]

class MessageRenderer {
    constructor() {
        this.isMarkedReady = false;
        this.isHighlightReady = false;
        this.initializeLibraries();
    }

    initializeLibraries() {
        // Check if marked is available
        if (typeof marked !== 'undefined') {
            this.isMarkedReady = true;
            this.configureMarked();
        } else {
            console.warn('marked.js not loaded, attempting to load from CDN');
            this.loadMarked();
        }

        // Check if highlight.js is available
        if (typeof hljs !== 'undefined') {
            this.isHighlightReady = true;
        } else {
            console.warn('highlight.js not loaded');
        }
    }

    loadMarked() {
        // Fallback to local if CDN fails
        const script = document.createElement('script');
        script.src = '/static/js/lib/marked.min.js';
        script.onload = () => {
            this.isMarkedReady = true;
            this.configureMarked();
        };
        script.onerror = () => {
            console.error('Failed to load marked.js from both CDN and local fallback');
        };
        document.head.appendChild(script);
    }

    configureMarked() {
        if (typeof marked === 'undefined') return;

        // Configure marked renderer
        const renderer = new marked.Renderer();

        // Custom code block renderer
        renderer.code = (code, language) => {
            const validLanguage = language && hljs.getLanguage(language) ? language : 'plaintext';
            const highlighted = this.isHighlightReady 
                ? hljs.highlight(code, { language: validLanguage }).value 
                : this.escapeHtml(code);

            return `
                <div class="code-block-container">
                    <div class="code-block-header">
                        <span class="code-language">${validLanguage}</span>
                        <button class="copy-code-btn" onclick="renderer.copyCode(this)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                            Copy
                        </button>
                    </div>
                    <pre><code class="hljs language-${validLanguage}">${highlighted}</code></pre>
                </div>
            `;
        };

        // Custom image renderer to ensure images render as <img> elements
        renderer.image = (href, title, text) => {
            const titleAttr = title ? ` title="${this.escapeHtml(title)}"` : '';
            const altAttr = text ? ` alt="${this.escapeHtml(text)}"` : '';
            return `<img src="${this.escapeHtml(href)}"${altAttr}${titleAttr} class="markdown-image" loading="lazy" />`;
        };

        // Configure marked with options
        marked.setOptions({
            renderer: renderer,
            gfm: true, // GitHub Flavored Markdown
            breaks: true, // Convert \n to <br>
            pedantic: false,
            sanitize: false, // We trust our content
            smartLists: true,
            smartypants: true,
            headerIds: true,
            mangle: false
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    render(markdown) {
        if (!markdown) return '';

        if (!this.isMarkedReady) {
            console.warn('marked.js not ready, returning plain text');
            return this.escapeHtml(markdown);
        }

        try {
            // Pre-process: Convert plain text image patterns to markdown
            let processedMarkdown = this.preprocessGeneratedImages(markdown);
            
            // Parse markdown
            let html = marked.parse(processedMarkdown);
            
            // Post-process: Add table containers and callout styles
            html = this.postProcessHTML(html);
            
            return html;
        } catch (error) {
            console.error('Error rendering markdown:', error);
            return this.escapeHtml(markdown);
        }
    }

    preprocessGeneratedImages(text) {
        // Convert plain text image patterns like:
        // ![Generated Image]
        // (static/generated_images/xxx.png)
        // These might appear on separate lines from backend output
        
        // Handle various line break scenarios
        // Pattern 1: Newline between ![alt] and (url) - most common
        text = text.replace(/!\[([^\]]*)\]\s*[\r\n]+\s*\(([^)]+)\)/g, (match, alt, src) => {
            console.log('[Renderer] Preprocessing multi-line image:', { alt, src: src.trim() });
            return `![${alt}](${src.trim()})`;
        });
        
        // Pattern 2: Extra whitespace or multiple newlines
        text = text.replace(/!\[([^\]]*)\]\s{2,}\(([^)]+)\)/g, (match, alt, src) => {
            console.log('[Renderer] Preprocessing whitespace-separated image:', { alt, src: src.trim() });
            return `![${alt}](${src.trim()})`;
        });
        
        // Pattern 3: Standard markdown images (normalization)
        text = text.replace(/!\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, src) => {
            const trimmedSrc = src.trim();
            // Only log if we're actually changing something
            if (src !== trimmedSrc) {
                console.log('[Renderer] Normalizing image:', { alt, src: trimmedSrc });
            }
            return `![${alt}](${trimmedSrc})`;
        });
        
        return text;
    }

    postProcessHTML(html) {
        // Create a temporary container to manipulate HTML
        const temp = document.createElement('div');
        temp.innerHTML = html;
        
        // 1. Wrap tables in scrollable containers
        const tables = temp.querySelectorAll('table');
        tables.forEach(table => {
            if (!table.parentElement.classList.contains('table-container')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'table-container';
                table.parentNode.insertBefore(wrapper, table);
                wrapper.appendChild(table);
            }
        });
        
        // 2. Process callout blocks (blockquotes starting with [!TYPE])
        const blockquotes = temp.querySelectorAll('blockquote');
        blockquotes.forEach(blockquote => {
            const firstChild = blockquote.firstElementChild;
            if (firstChild && firstChild.textContent) {
                const text = firstChild.textContent.trim();
                const calloutMatch = text.match(/^\[!(NOTE|WARNING|INFO|TIP|IMPORTANT|CAUTION)\]/i);
                
                if (calloutMatch) {
                    const calloutType = calloutMatch[1].toLowerCase();
                    blockquote.classList.add('callout', `callout-${calloutType}`);
                    
                    // Remove the [!TYPE] marker from content
                    firstChild.textContent = text.replace(/^\[!(?:NOTE|WARNING|INFO|TIP|IMPORTANT|CAUTION)\]\s*/i, '');
                }
            }
        });
        
        // 3. Apply highlight.js to any code blocks that weren't processed by marked
        if (this.isHighlightReady) {
            const codeBlocks = temp.querySelectorAll('pre code:not(.hljs)');
            codeBlocks.forEach(block => {
                if (block.className.includes('language-')) {
                    hljs.highlightElement(block);
                }
            });
        }
        
        return temp.innerHTML;
    }

    copyCode(button) {
        const codeBlock = button.closest('.code-block-container');
        const code = codeBlock.querySelector('code').textContent;
        
        navigator.clipboard.writeText(code).then(() => {
            const originalText = button.innerHTML;
            button.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                Copied!
            `;
            button.classList.add('copied');
            
            setTimeout(() => {
                button.innerHTML = originalText;
                button.classList.remove('copied');
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy code:', err);
        });
    }

    renderMessage(content, isUser = false) {
        if (isUser) {
            // User messages: simple, no markdown rendering
            return this.escapeHtml(content);
        } else {
            // Assistant messages: full markdown rendering
            return this.render(content);
        }
    }
}

// Create global renderer instance
const renderer = new MessageRenderer();
