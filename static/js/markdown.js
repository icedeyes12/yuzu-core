// markme.js - 
class MarkdownParser {
    static parse(text) {
        if (!text) return '';
        let html = String(text);

        console.log("Processing text length:", html.length);

        // Parse code block DULU - lindungi dari parsing lain
        html = this.protectAndParseCodeBlocks(html);

        // Parse footnotes sebelum yang lain
        html = this.parseFootnotes(html);

        // Parse blockquotes dengan nested support
        html = this.parseBlockquotes(html);

        // Parse tabel
        html = this.parseTables(html);

        // Parse lists dengan nested support
        html = this.parseLists(html);

        // Parse definition lists
        html = this.parseDefinitionLists(html);

        // Parse semua heading levels (1-6)
        html = html.replace(/^###### (.*?)$/gm, '<h6>$1</h6>');
        html = html.replace(/^##### (.*?)$/gm, '<h5>$1</h5>');
        html = html.replace(/^#### (.*?)$/gm, '<h4>$1</h4>');
        html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');
        
        // Parse garis horizontal
        html = html.replace(/^---$/gm, '<hr>');
        html = html.replace(/^\*\*\*$/gm, '<hr>');
        html = html.replace(/^___$/gm, '<hr>');

        // Parse inline markdown
        html = this.parseInlineMarkdown(html);

        // Handle line break
        html = this.convertLineBreaks(html);
        
        // Kembalikan code block
        html = this.restoreProtectedCodeBlocks(html);

        // Parse abbreviations terakhir
        html = this.parseAbbreviations(html);
        
        return html;
    }

    static protectAndParseCodeBlocks(html) {
        this.codeBlockPlaceholders = [];
        let placeholderIndex = 0;
        
        const processedHtml = html.replace(/```([\w+-]*)\s*\n([\s\S]*?)\n```/g, (full, lang, code) => {
            console.log("Found code block:", { 
                lang: lang || 'text', 
                codeLength: code.length
            });
            
            const placeholder = `__CODE_BLOCK_${placeholderIndex}__`;
            this.codeBlockPlaceholders.push({
                placeholder,
                html: this.createCodeBlock(lang, code.trim())
            });
            placeholderIndex++;
            
            return placeholder;
        });
        
        return processedHtml;
    }

    static restoreProtectedCodeBlocks(html) {
        let restoredHtml = html;
        this.codeBlockPlaceholders.forEach(item => {
            restoredHtml = restoredHtml.replace(item.placeholder, item.html);
        });
        this.codeBlockPlaceholders = [];
        return restoredHtml;
    }

    static parseFootnotes(html) {
        // Parse footnote references [^1]
        html = html.replace(/\[\^(\d+)\]/g, '<sup id="fnref:$1"><a href="#fn:$1" class="footnote-ref">$1</a></sup>');
        
        // Parse footnote definitions [^1]: content
        const footnoteRegex = /\[\^(\d+)\]:\s*(.*?)(?=\n\[\^\d+\]:|\n\n|$)/gs;
        if (footnoteRegex.test(html)) {
            html = html.replace(footnoteRegex, 
                '<li id="fn:$1" class="footnote-item"><span class="footnote-number">$1.</span> $2 <a href="#fnref:$1" class="footnote-backref">↩</a></li>');
            
            // Wrap footnotes in container
            html = html.replace(/(<li class="footnote-item">.*<\/li>)/s, 
                '<div class="footnotes"><hr><ol class="footnotes-list">$1</ol></div>');
        }
        
        return html;
    }

    static parseBlockquotes(html) {
        const parts = html.split(/(__CODE_BLOCK_\d+__)/g);
        let result = '';

        for (let i = 0; i < parts.length; i++) {
            if (i % 2 === 0) {
                let text = parts[i];
                
                // Process blockquotes line by line - FIXED VERSION
                const lines = text.split('\n');
                const processedLines = [];
                let inBlockquote = false;
                let currentLevel = 0;
                let blockquoteContent = [];

                const closeBlockquote = (level) => {
                    if (blockquoteContent.length > 0) {
                        let blockquoteHtml = blockquoteContent.join('\n');
                        // Parse inline markdown dalam blockquote
                        blockquoteHtml = this.parseInlineMarkdown(blockquoteHtml);
                        // Add nested blockquote tags based on level
                        for (let l = 0; l < level; l++) {
                            blockquoteHtml = `<blockquote>${blockquoteHtml}</blockquote>`;
                        }
                        processedLines.push(blockquoteHtml);
                        blockquoteContent = [];
                    }
                };

                for (const line of lines) {
                    const match = line.match(/^(>+)\s*(.*)$/);
                    
                    if (match) {
                        const level = match[1].length;
                        const content = match[2].trim();
                        
                        if (!inBlockquote || level !== currentLevel) {
                            closeBlockquote(currentLevel);
                            inBlockquote = true;
                            currentLevel = level;
                        }
                        
                        if (content) {
                            blockquoteContent.push(content);
                        } else {
                            // Empty line dalam blockquote - tetap pertahankan spacing
                            blockquoteContent.push('<br>');
                        }
                    } else {
                        closeBlockquote(currentLevel);
                        inBlockquote = false;
                        currentLevel = 0;
                        // Only add non-empty lines
                        if (line.trim() !== '' || processedLines.length === 0) {
                            processedLines.push(line);
                        }
                    }
                }

                closeBlockquote(currentLevel);
                result += processedLines.join('\n');
            } else {
                result += parts[i];
            }
        }

        return result;
    }

    static parseDefinitionLists(html) {
        const parts = html.split(/(__CODE_BLOCK_\d+__)/g);
        let result = '';

        for (let i = 0; i < parts.length; i++) {
            if (i % 2 === 0) {
                let text = parts[i];
                
                // Match pattern: term\n: definition
                text = text.replace(/^(.+)\n:\s+(.+)$/gm, 
                    '<div class="definition-item"><dt class="definition-term">$1</dt><dd class="definition-desc">$2</dd></div>');
                
                // Multiple definitions for same term
                text = text.replace(/^(<dd class="definition-desc">[^<]+)<\/dd>\n:\s+(.+)$/gm, 
                    '$1<br>$2</dd>');
                
                // Wrap consecutive definition items
                text = text.replace(/(<div class="definition-item">.*?<\/div>\n?)+/g, 
                    '<dl class="definition-list">$&</dl>');
                
                result += text;
            } else {
                result += parts[i];
            }
        }

        return result;
    }
//comment for indentation helper
    static parseLists(html) {
        const parts = html.split(/(__CODE_BLOCK_\d+__)/g);
        let result = '';

        for (let i = 0; i < parts.length; i++) {
            if (i % 2 === 0) {
                let text = parts[i];
                
                // Process lists with proper nesting - FIXED VERSION
                const lines = text.split('\n');
                const processedLines = [];
                let listStack = [];
                let currentIndent = -1;

                const closeLists = (targetIndent) => {
                    while (listStack.length > 0 && listStack[listStack.length - 1].indent >= targetIndent) {
                        const list = listStack.pop();
                        processedLines.push(`</${list.type}>`);
                    }
                };

                for (const line of lines) {
                    // Check for task list items
                    const taskMatch = line.match(/^(\s*)- \[([ x])\]\s+(.*)$/);
                    // Check for unordered list items
                    const ulMatch = line.match(/^(\s*)[\*\+-]\s+(.*)$/);
                    // Check for ordered list items - FIXED: ambil seluruh konten termasuk angka
                    const olMatch = line.match(/^(\s*)(\d+\..*)$/);

                    if (taskMatch || ulMatch || olMatch) {
                        const match = taskMatch || ulMatch || olMatch;
                        const indent = match[1].length;
                        const content = taskMatch ? match[3] : (olMatch ? match[2] : match[2]);
                        const isTask = !!taskMatch;
                        const isChecked = taskMatch ? match[2] === 'x' : false;
                        const isOrdered = !!olMatch;
                        
                        // FIX: Selalu gunakan ul untuk menghindari auto-numbering browser
                        const listType = 'ul'; // Selalu ul, bahkan untuk ordered list
                        const itemClass = isTask ? 'task-list-item' + (isChecked ? ' checked' : '') : '';
                        const checkbox = isTask ? `<input type="checkbox" ${isChecked ? 'checked' : ''} disabled>` : '';

                        closeLists(indent);

                        if (listStack.length === 0 || listStack[listStack.length - 1].indent < indent) {
                            // Start new nested list
                            processedLines.push(`<${listType}${isTask ? ' class="contains-task-list"' : ''}>`);
                            listStack.push({ type: listType, indent });
                        } else if (listStack.length > 0 && listStack[listStack.length - 1].type !== listType) {
                            // Switch list type at same indent level
                            closeLists(indent - 1);
                            processedLines.push(`<${listType}${isTask ? ' class="contains-task-list"' : ''}>`);
                            listStack.push({ type: listType, indent });
                        }

                        // FIX: Untuk semua list, sertakan seluruh konten (termasuk angka)
                        if (isTask) {
                            processedLines.push(`<li class="${itemClass}">${checkbox}${this.parseInlineMarkdownInList(content)}</li>`);
                        } else {
                            processedLines.push(`<li class="${itemClass}">${this.parseInlineMarkdownInList(content)}</li>`);
                        }
                    } else {
                        closeLists(-1);
                        // Only add non-empty lines to avoid extra spacing
                        if (line.trim() !== '') {
                            processedLines.push(line);
                        }
                    }
                }

                closeLists(-1);
                result += processedLines.join('\n');
            } else {
                result += parts[i];
            }
        }

        return result;
    }

    static parseTables(html) {
        const parts = html.split(/(__CODE_BLOCK_\d+__)/g);
        let result = '';
        
        for (let i = 0; i < parts.length; i++) {
            if (i % 2 === 0) {
                result += parts[i].replace(/(?:\|.*\|\s*\n\|[-:\s|]+\|\s*\n(?:\|.*\|\s*\n)*)/g, (tableBlock) => {
                    console.log("Found table:", tableBlock.substring(0, 100) + '...');
                    return this.createTable(tableBlock);
                });
            } else {
                result += parts[i];
            }
        }
        
        return result;
    }

    static parseInlineMarkdown(html) {
        const parts = html.split(/(__CODE_BLOCK_\d+__)/g);
        let result = '';

        for (let i = 0; i < parts.length; i++) {
            if (i % 2 === 0) {
                let text = parts[i];

                // Parse links and images FIRST
                text = this.parseLinksAndImages(text);

                // Parse superscript and subscript
                text = text.replace(/\^([^\^]+)\^/g, '<sup>$1</sup>');
                text = text.replace(/~([^~]+)~/g, '<sub>$1</sub>');

                // Parse keyboard keys - handle both [[key]] and `key` styles
                text = text.replace(/\[\[([^\]]+)\]\]/g, '<kbd class="keyboard-key">$1</kbd>');
                text = text.replace(/`([^`\n]+?)`/g, (match, code) => {
                    // Don't convert if it's already a keyboard key or looks like a key combination
                    if (code.match(/^(Ctrl|Alt|Shift|Cmd|Enter|Space|Tab|Esc|Delete|Backspace|[A-Z])(\+\w+)*$/i)) {
                        return `<kbd class="keyboard-key">${code}</kbd>`;
                    }
                    return `<code class="inline-code">${code}</code>`;
                });

                // Parse bold dan italic dengan nesting yang benar
                text = text.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
                text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                text = text.replace(/__(.*?)__/g, '<strong>$1</strong>');
                text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');

                // Lindungi underscore di dalam kata
                text = text.replace(/(\w)_(\w)/g, '$1&#95;$2');

                // Hanya italic underscore yang jelas sebagai markdown
                text = text.replace(/(^|[^_])_(?!_)(.*?)_(?!_)([^_]|$)/g, '$1<em>$2</em>$3');

                // Strikethrough
                text = text.replace(/~~(.*?)~~/g, '<del>$1</del>');

                result += text;
            } else {
                result += parts[i];
            }
        }

        return result;
    }

    static parseLinksAndImages(text) {
        // Parse images: ![alt text](url)
        text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, 
            '<img src="$2" alt="$1" class="markdown-image" loading="lazy">');

        // Parse links: [text](url)
        text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, 
            '<a href="$2" target="_blank" rel="noopener noreferrer" class="markdown-link">$1</a>');

        // Parse bare URLs
        text = text.replace(/(https?:\/\/[^\s<]+[^<.,:;"')\]\s])/g, 
            '<a href="$1" target="_blank" rel="noopener noreferrer" class="markdown-link">$1</a>');

        return text;
    }

    static parseAbbreviations(html) {
        const abbreviations = {};
        
        // Capture abbreviation definitions
        html = html.replace(/\*\[([^\]]+)\]:\s*(.+)/g, (match, abbr, definition) => {
            abbreviations[abbr] = definition;
            return '';
        });
        
        // Replace abbreviations in text
        Object.keys(abbreviations).forEach(abbr => {
            const regex = new RegExp(`\\b${abbr}\\b`, 'g');
            html = html.replace(regex, `<abbr title="${abbreviations[abbr]}">${abbr}</abbr>`);
        });
        
        return html;
    }

    static parseInlineMarkdownInList(text) {
        if (!text) return '';
        
        let html = String(text);
        
        // Parse inline markdown dalam list items
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        html = html.replace(/`([^`\n]+?)`/g, '<code class="inline-code">$1</code>');
        html = html.replace(/~~(.*?)~~/g, '<del>$1</del>');
        
        // Parse links dalam list items
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, 
            '<a href="$2" target="_blank" rel="noopener noreferrer" class="markdown-link">$1</a>');
        
        return html;
    }

    static parseInlineMarkdownInTable(text) {
        if (!text) return '';
        
        let html = String(text);
        
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        html = html.replace(/`([^`\n]+?)`/g, '<code class="inline-code">$1</code>');
        
        return html;
    }

    static parseTableRow(row) {
        const cells = [];
        let currentCell = '';
        let inCode = false;
        
        for (let i = 0; i < row.length; i++) {
            const char = row[i];
            const nextChar = row[i + 1];
            
            if (char === '`') {
                inCode = !inCode;
                currentCell += char;
            } else if (char === '\\' && nextChar === '|') {
                currentCell += '|';
                i++;
            } else if (char === '|' && !inCode) {
                if (i > 0 || currentCell.trim()) {
                    cells.push(currentCell);
                }
                currentCell = '';
            } else {
                currentCell += char;
            }
        }
        
        if (currentCell.trim()) {
            cells.push(currentCell);
        }
        
        return cells.filter(cell => cell.trim() !== '');
    }

    static createTable(tableBlock) {
        const lines = tableBlock.trim().split('\n').filter(line => line.trim());
        
        if (lines.length < 2) return tableBlock;
        
        const tableHtml = ['<div class="table-container"><table>'];
        
        const headerCells = this.parseTableRow(lines[0]);
        tableHtml.push('<thead><tr>');
        headerCells.forEach(cell => {
            tableHtml.push(`<th>${this.parseInlineMarkdownInTable(cell.trim())}</th>`);
        });
        tableHtml.push('</tr></thead>');
        
        const separatorRow = lines[1];
        if (!separatorRow.includes('-')) {
            return tableBlock;
        }
        
        tableHtml.push('<tbody>');
        for (let i = 2; i < lines.length; i++) {
            const rowCells = this.parseTableRow(lines[i]);
            tableHtml.push('<tr>');
            rowCells.forEach(cell => {
                tableHtml.push(`<td>${this.parseInlineMarkdownInTable(cell.trim())}</td>`);
            });
            tableHtml.push('</tr>');
        }
        tableHtml.push('</tbody></table></div>');
        
        return tableHtml.join('');
    }

    static createCodeBlock(language, code) {
        const cleanLanguage = language ? language.trim().toLowerCase() : 'text';
        const displayName = this.getLanguageDisplayName(cleanLanguage);

        const escapedCode = code
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        return `<div class="code-block-container">
    <div class="code-header">
        <span class="language-name">${displayName}</span>
        <button class="copy-code-btn" onclick="copyCodeToClipboard(this)">
            <span class="copy-text">Copy</span>
        </button>
    </div>
    <pre><code class="language-${cleanLanguage}">${escapedCode}</code></pre>
</div>`;
    }

    static getLanguageDisplayName(lang) {
        const names = {
            'python': 'PYTHON', 'javascript': 'JAVASCRIPT', 'js': 'JAVASCRIPT',
            'html': 'HTML', 'css': 'CSS', 'json': 'JSON', 'java': 'JAVA',
            'cpp': 'C++', 'c++': 'C++', 'c': 'C', 'rust': 'RUST', 'go': 'GO',
            'bash': 'BASH', 'shell': 'SHELL', 'text': 'TEXT',
            'typescript': 'TYPESCRIPT', 'ts': 'TYPESCRIPT',
            'php': 'PHP', 'ruby': 'RUBY', 'sql': 'SQL',
            'markdown': 'MARKDOWN', 'md': 'MARKDOWN',
            'yaml': 'YAML', 'yml': 'YAML',
            'xml': 'XML', 'svg': 'SVG'
        };
        return names[lang] || (lang ? lang.toUpperCase() : 'TEXT');
    }

    static convertLineBreaks(html) {
        const parts = html.split(/(__CODE_BLOCK_\d+__|<div class="table-container">[\s\S]*?<\/div>|<pre[\s\S]*?<\/pre>|<table[\s\S]*?<\/table>|<h[1-6]>.*?<\/h[1-6]>|<hr>|<ul>.*?<\/ul>|<ol>.*?<\/ol>|<li>.*?<\/li>|<blockquote[^>]*>.*?<\/blockquote>|<dl>.*?<\/dl>|<dt>.*?<\/dt>|<dd>.*?<\/dd>)/g);
        let result = '';
        
        for (let i = 0; i < parts.length; i++) {
            if (i % 2 === 0 && parts[i]) {
                result += parts[i].replace(/\n/g, '<br>');
            } else {
                result += parts[i];
            }
        }
        
        return result;
    }

    static escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    static parseWithEmojis(text) {
        return this.parse(text);
    }

    static highlightCodeBlocks(container = document) {
        if (typeof hljs === 'undefined') {
            console.log('Highlight.js not loaded');
            return 0;
        }

        const blocks = container.querySelectorAll('pre code');
        let count = 0;

        blocks.forEach(block => {
            try {
                block.className = block.className.replace(/hljs|language-\w+/g, '');
                
                const match = block.className.match(/language-(\w+)/);
                if (match) {
                    block.className = `language-${match[1]}`;
                }
                
                hljs.highlightElement(block);
                count++;
            } catch (e) {
                console.error('Error highlighting:', e);
                block.classList.add('hljs');
            }
        });

        console.log(`Highlighted ${count} code blocks`);
        return count;
    }
}

// Inisialisasi array placeholder code block
MarkdownParser.codeBlockPlaceholders = [];

// FUNGSI COPY
function copyCodeToClipboard(button) {
    if (!button) return;
    
    try {
        const codeContainer = button.closest('.code-block-container');
        const codeElement = codeContainer.querySelector('code');
        if (!codeElement) return;

        const codeText = codeElement.textContent || codeElement.innerText;
        const copyText = button.querySelector('.copy-text');

        navigator.clipboard.writeText(codeText).then(() => {
            const originalText = copyText.textContent;
            copyText.textContent = 'Copied!';
            button.classList.add('copied');
            
            setTimeout(() => {
                copyText.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);
        }).catch(err => {
            console.log('Using fallback copy method');
            const textArea = document.createElement('textarea');
            textArea.value = codeText;
            textArea.style.position = 'fixed';
            textArea.style.opacity = '0';
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            
            const originalText = copyText.textContent;
            copyText.textContent = 'Copied!';
            button.classList.add('copied');
            setTimeout(() => {
                copyText.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);
        });
    } catch (error) {
        console.error('Error copying:', error);
    }
}

// INISIALISASI
document.addEventListener('DOMContentLoaded', () => {
    console.log('Markdown parser loaded with complete features');
    
    if (typeof hljs !== 'undefined') {
        hljs.configure({ 
            tabReplace: '    ',
            ignoreUnescapedHTML: true
        });
        
        setTimeout(() => {
            const count = MarkdownParser.highlightCodeBlocks();
            console.log(`Initially highlighted ${count} code blocks`);
        }, 1000);
    }
});

window.MarkdownParser = MarkdownParser;
window.copyCodeToClipboard = copyCodeToClipboard;
window.highlightCodeBlocks = MarkdownParser.highlightCodeBlocks.bind(MarkdownParser);