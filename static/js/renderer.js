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
            const hasLanguage = this.isHighlightReady && typeof hljs !== 'undefined' && language && hljs.getLanguage(language);
            const validLanguage = hasLanguage ? language : 'plaintext';
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
            const { href: resolvedHref, title: resolvedTitle, text: resolvedText } = this.resolveImageToken(href, title, text);
            const normalizedHref = this.normalizeImagePath(resolvedHref);
            const titleAttr = resolvedTitle ? ` title="${this.escapeHtml(resolvedTitle)}"` : '';
            const altAttr = resolvedText ? ` alt="${this.escapeHtml(resolvedText)}"` : '';
            const errorHandler = `onerror="this.onerror=null; this.outerHTML='<div class=\\'image-error\\'>⚠️ Image not found: ${this.escapeHtml(resolvedText || 'Image')}</div>';"`;
            return `<img src="${this.escapeHtml(normalizedHref)}"${altAttr}${titleAttr} class="markdown-image" loading="lazy" ${errorHandler} />`;
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

    normalizeImagePath(path) {
        if (!path) return path;
        const { href: rawPathValue } = this.resolveImageToken(path);
        let rawPath = rawPathValue;
        if (typeof rawPath !== 'string') {
            rawPath = String(rawPath);
        }
        const cleaned = rawPath.trim().replace(/\\/g, '/');
        if (/^(https?:)?\/\//i.test(cleaned) || cleaned.startsWith('data:') || cleaned.startsWith('/')) {
            return cleaned;
        }
        if (cleaned.startsWith('static/')) {
            return `/${cleaned}`;
        }
        if (cleaned.startsWith('uploads/') || cleaned.startsWith('generated_images/')) {
            return `/static/${cleaned}`;
        }
        return cleaned;
    }

    render(markdown) {
        if (markdown === null || markdown === undefined) return '';
        const safeMarkdown = typeof markdown === 'string' ? markdown : String(markdown);

        if (!this.isMarkedReady) {
            console.warn('marked.js not ready, returning plain text');
            return this.renderWithoutMarked(safeMarkdown);
        }

        try {
            // Pre-process: Convert plain text image patterns to markdown
            let processedMarkdown = this.preprocessGeneratedImages(safeMarkdown);
            
            // Parse markdown
            let html = marked.parse(processedMarkdown);
            
            // Post-process: Add table containers and callout styles
            html = this.postProcessHTML(html);
            
            return html;
        } catch (error) {
            console.error('Render error:', error, safeMarkdown);
            return `<pre class="render-error">${this.escapeHtml(safeMarkdown)}</pre>`;
        }
    }

    preprocessGeneratedImages(text) {
        // Convert plain text image patterns like:
        // ! [Generated Image]
        // (static/generated_images/xxx.png)
        // These might appear on separate lines from backend output
        // Note: Backend sometimes adds space after ! like "! [text]" instead of "![text]"
        
        const sourceText = typeof text === 'string' ? text : String(text || '');
        console.log('[Renderer] Preprocessing images, input length:', sourceText.length);
        
        // Single comprehensive pattern: Handle all variations
        // Matches: ! [alt] or ![alt] followed by optional whitespace/newlines then (url)
        const imagePattern = /!\s*\[([^\]]*)\]\s*\n?\s*\(([^)]+)\)/g;
        
        let matchCount = 0;
        let normalizedText = sourceText.replace(/\r\n/g, '\n');
        normalizedText = normalizedText.replace(imagePattern, (match, alt, src) => {
            matchCount++;
            const trimmedSrc = src.trim();
            // Encode spaces in image paths so marked.js can parse them correctly
            const encodedSrc = trimmedSrc.replace(/ /g, '%20');
            console.log(`[Renderer] Found image #${matchCount}:`, { 
                alt: alt, 
                src: encodedSrc,
                originalMatch: match.substring(0, 50) + (match.length > 50 ? '...' : '')
            });
            return `![${alt}](${encodedSrc})`;
        });
        
        if (matchCount > 0) {
            console.log(`[Renderer] Preprocessed ${matchCount} images`);
        }
        
        return normalizedText;
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

    renderWithoutMarked(markdown) {
        try {
            const processed = this.preprocessGeneratedImages(markdown);
            let html = this.escapeHtml(processed);

            html = html.replace(/!\s*\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, src) => {
                const normalizedHref = this.normalizeImagePath(src);
                const safeAlt = this.escapeHtml(alt || 'Image');
                const safeSrc = this.escapeHtml(normalizedHref);
                return `<img src="${safeSrc}" alt="${safeAlt}" class="markdown-image" loading="lazy" />`;
            });

            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/\n/g, '<br>');

            return html;
        } catch (error) {
            console.error('Render error:', error, markdown);
            return `<pre class="render-error">${this.escapeHtml(markdown)}</pre>`;
        }
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
        if (isUser && !this.containsImageMarkdown(content)) {
            // User messages: escape HTML and preserve newlines
            return this.escapeHtml(content).replace(/\n/g, '<br>');
        } else {
            // Assistant messages: full markdown rendering
            return this.render(content);
        }
    }

    containsImageMarkdown(content) {
        if (!content) return false;
        return /!\s*\[[^\]]*\]\s*\n?\s*\([^)]+\)/.test(String(content));
    }

    resolveImageToken(href, title = '', text = '') {
        if (href && typeof href === 'object') {
            return {
                href: href.href || href.url || '',
                title: href.title || title || '',
                text: href.text || text || ''
            };
        }
        return { href, title, text };
    }
}

// Create global renderer instance
const renderer = new MessageRenderer();
