// FILE: static/js/renderer.js
// DESCRIPTION: Markdown renderer using marked.js with syntax highlighting

// ==================== CENTRALIZED CLIPBOARD UTILITY ====================
// Single source of truth for all copy-to-clipboard operations.
// Provides consistent visual feedback across code blocks, tables, and messages.
const ClipboardUtils = {
	// SVG icons for consistent button appearance
	ICONS: {
		copy: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
			<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
		</svg>`,
		check: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<polyline points="20 6 9 17 4 12"></polyline>
		</svg>`,
	},

	// Default feedback duration in milliseconds
	FEEDBACK_DURATION: 2000,

	/**
	 * Copy text to clipboard with optional button feedback.
	 * The button param receives visual success feedback (icon change + "Copied!" text).
	 * @param {string} text - Text to copy
	 * @param {HTMLElement} [button] - Optional button element for visual feedback
	 * @param {object} [options] - Optional configuration
	 * @param {number} [options.duration] - Feedback duration in ms (default: 2000)
	 * @param {string} [options.successText] - Text to show on success (default: "Copied!")
	 * @returns {Promise<boolean>} - True if copy succeeded
	 */
	async copyText(text, button = null, options = {}) {
		const { duration = this.FEEDBACK_DURATION, successText = "Copied!" } =
			options;

		try {
			await navigator.clipboard.writeText(text);
			console.log("Copied to clipboard");

			if (button) {
				this._showSuccess(button, successText, duration);
			}
			return true;
		} catch (err) {
			console.error("Failed to copy to clipboard:", err);
			return false;
		}
	},

	/**
	 * Show success feedback on a button element.
	 * Restores original content after the specified duration.
	 * @private
	 */
	_showSuccess(button, successText, duration) {
		const originalHTML = button.innerHTML;
		button.innerHTML = `${this.ICONS.check}${successText}`;
		button.classList.add("copied");

		setTimeout(() => {
			button.innerHTML = originalHTML;
			button.classList.remove("copied");
		}, duration);
	},
};

// ==================== EVENT DELEGATION FOR COPY BUTTONS ====================
// Single click handler on document for all dynamically-added copy buttons
document.addEventListener("click", (event) => {
	const target = event.target;

	// Handle copy-code-btn
	const copyCodeBtn = target.closest('[data-action="copy-code"]');
	if (copyCodeBtn) {
		const codeBlock = copyCodeBtn.closest(".code-block-container");
		const code = codeBlock?.querySelector("code")?.textContent || "";
		ClipboardUtils.copyText(code, copyCodeBtn);
		return;
	}

	// Handle copy-mermaid-code
	const copyMermaidBtn = target.closest('[data-action="copy-mermaid-code"]');
	if (copyMermaidBtn) {
		const encodedCode = copyMermaidBtn.getAttribute("data-mermaid-code") || "";
		const code = decodeURIComponent(encodedCode);
		ClipboardUtils.copyText(code, copyMermaidBtn);
		return;
	}

	// Handle copy-table
	const copyTableBtn = target.closest('[data-action="copy-table"]');
	if (copyTableBtn) {
		const table = copyTableBtn
			.closest(".table-container")
			?.querySelector("table");
		if (table) {
			copyTable(table, copyTableBtn);
		}
		return;
	}

	// Handle copy-message
	const copyMsgBtn = target.closest('[data-action="copy-message"]');
	if (copyMsgBtn) {
		// Try to get content from data-message-content attr
		const content = copyMsgBtn.getAttribute("data-message-content") || "";
		ClipboardUtils.copyText(content, copyMsgBtn);
		return;
	}

	// Handle HTML preview
	const previewBtn = target.closest('[data-action="preview-html"]');
	if (previewBtn) {
		const encodedCode = previewBtn.getAttribute("data-code") || "";
		showHtmlPreviewModal(encodedCode);
		return;
	}
});

/**
 * Copy table content as TSV
 */
function copyTable(table, button) {
	const rows = table.querySelectorAll("tr");
	const tsvLines = [];

	rows.forEach((row) => {
		const cells = row.querySelectorAll("th, td");
		const cellTexts = Array.from(cells).map((cell) => {
			return cell.textContent.trim().replace(/\n/g, " ");
		});
		tsvLines.push(cellTexts.join("\t"));
	});

	const tsv = tsvLines.join("\n");
	ClipboardUtils.copyText(tsv, button);
}

/**
 * Show HTML preview modal
 */
function showHtmlPreviewModal(encodedCode) {
	const rawCode = decodeURIComponent(encodedCode || "");
	const modal = document.getElementById("html-preview-modal");
	const iframe = document.getElementById("preview-iframe");
	if (!modal || !iframe || !rawCode) return;

	// Unescape HTML entities (code may be double-encoded from marked.js escaping)
	const code = rawCode
		.replace(/&lt;/g, "<")
		.replace(/&gt;/g, ">")
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.replace(/&#x27;/g, "'")
		.replace(/&amp;/g, "&");

	modal.classList.add("active");
	document.body.style.overflow = "hidden";
	iframe.srcdoc = code;
}

// ==================== RENDERER CLASS ====================
class MessageRenderer {
	constructor() {
		this.isMermaidReady = false;
		this.isMarkedReady = false;
		this.isHighlightReady = false;
		this.isKatexReady = false;
		this.initializeLibraries();
	}

	initializeLibraries() {
		// Check if marked is available
		if (typeof marked !== "undefined") {
			this.isMarkedReady = true;
			this.configureMarked();
		} else {
			console.warn("marked.js not loaded, attempting to load from CDN");
			this.loadMarked();
		}

		// Check if highlight.js is available
		if (typeof hljs !== "undefined") {
			this.isHighlightReady = true;
			hljs.configure({ ignoreUnescapedHTML: true });
		} else {
			console.warn("highlight.js not loaded");
		}

		// Initialize mermaid.js
		if (typeof mermaid !== "undefined") {
			const themeVariables = this._getMermaidThemeVariables();
			mermaid.initialize({
				startOnLoad: false,
				theme: "base",
				themeVariables: themeVariables,
				securityLevel: "loose",
				flowchart: {
					useMaxWidth: true,
					htmlLabels: true,
					curve: "basis",
				},
				sequence: {
					useMaxWidth: true,
				},
				gantt: {
					useMaxWidth: true,
				},
				er: {
					useMaxWidth: true,
				},
			});
			this.isMermaidReady = true;
			console.log("Mermaid initialized successfully");
		}

		// Check if KaTeX is available
		if (typeof katex !== "undefined") {
			this.isKatexReady = true;
			console.log("KaTeX initialized successfully");
		}
	}

	loadMarked() {
		// Try CDN first, then fallback to local
		const cdnUrl =
			"https://cdn.jsdelivr.net/npm/marked@18.0.2/lib/marked.umd.js";
		const localUrl = "/static/js/lib/marked.umd.js";

		const script = document.createElement("script");
		script.src = cdnUrl;
		script.onload = () => {
			this.isMarkedReady = true;
			this.configureMarked();
			console.log("marked.js v18.0.2 loaded from CDN");
		};
		script.onerror = () => {
			// Try local fallback
			const fallbackScript = document.createElement("script");
			fallbackScript.src = localUrl;
			fallbackScript.onload = () => {
				this.isMarkedReady = true;
				this.configureMarked();
				console.log("marked.js loaded from local fallback");
			};
			fallbackScript.onerror = () => {
				console.error(
					"Failed to load marked.js from both CDN and local fallback",
				);
			};
			document.head.appendChild(fallbackScript);
		};
		document.head.appendChild(script);
	}

	normalizeLanguageAlias(lang) {
		if (!lang) return null;
		const lower = lang.toLowerCase().trim();
		if (!lower || lower === "text" || lower === "plaintext") return null;

		const familyMap = {
			// Shell / CLI family → bash
			sh: "bash",
			zsh: "bash",
			fish: "bash",
			shell: "bash",
			docker: "bash",
			dockerfile: "bash",
			compose: "bash",
			make: "bash",
			makefile: "bash",
			cmake: "bash",
			powershell: "bash",
			ps1: "bash",
			pwsh: "bash",
			bat: "bash",
			cmd: "bash",

			// JavaScript family → javascript
			js: "javascript",
			mjs: "javascript",
			cjs: "javascript",
			jsx: "javascript",
			node: "javascript",
			deno: "javascript",

			// TypeScript family → typescript
			ts: "typescript",
			tsx: "typescript",

			// SQL family → sql
			mysql: "sql",
			postgres: "sql",
			postgresql: "sql",
			sqlite: "sql",
			tsql: "sql",
			plsql: "sql",
			mssql: "sql",

			// Config / data family → json
			yml: "json",
			yaml: "json",
			toml: "json",
			ini: "json",
			env: "json",
			dotenv: "json",
			terraform: "json",
			hcl: "json",
			tf: "json",

			// Markup family → xml
			html: "html",
			xhtml: "html",
			svg: "xml",
			rss: "xml",
			atom: "xml",

			// Python aliases → python
			py: "python",
			python3: "python",

			// Markdown aliases → markdown
			md: "markdown",
			mdx: "markdown",

			// Ruby aliases → ruby
			rb: "ruby",

			// Rust aliases → rust
			rs: "rust",

			// Kotlin aliases → kotlin
			kt: "kotlin",
			kts: "kotlin",

			// C# aliases → csharp
			cs: "csharp",

			// C++ aliases → cpp
			hpp: "cpp",
			cc: "cpp",
			cxx: "cpp",
			hxx: "cpp",

			// C aliases → c
			h: "c",

			// Objective-C aliases → objectivec
			objc: "objectivec",
			mm: "objectivec",

			// VB aliases → vbnet
			vb: "vbnet",

			// GraphQL aliases → graphql
			gql: "graphql",

			// LaTeX aliases → latex
			tex: "latex",

			// Assembly aliases → x86asm
			asm: "x86asm",
		};

		return familyMap[lower] || lower;
	}

	configureMarked() {
		if (typeof marked === "undefined") return;

		// Configure marked renderer
		const renderer = new marked.Renderer();

		// Custom math extension for KaTeX
		const mathExtension = {
			name: "math",
			level: "inline",
			start(src) {
				return src.indexOf("$");
			},
			tokenizer(src, _tokens) {
				// Block math: $$ ... $$
				const blockRule = /^\$\$([\s\S]+?)\$\$/;
				const blockMatch = blockRule.exec(src);
				if (blockMatch) {
					return {
						type: "math",
						raw: blockMatch[0],
						text: blockMatch[1].trim(),
						displayMode: true,
					};
				}

				// Inline math: $ ... $
				// Requirements: $ followed by non-space, ends with non-space followed by $
				// Negative lookahead for digit to handle $50 and $100 cases
				const inlineRule = /^\$([^\s$][^$]*?[^\s$])\$(?!\d)/;
				const inlineRuleSimple = /^\$([^$\s])\$(?!\d)/;

				const inlineMatch = inlineRule.exec(src) || inlineRuleSimple.exec(src);
				if (inlineMatch) {
					return {
						type: "math",
						raw: inlineMatch[0],
						text: inlineMatch[1],
						displayMode: false,
					};
				}
				return undefined;
			},
			renderer(token) {
				if (typeof katex === "undefined") return token.raw;
				try {
					return katex.renderToString(token.text, {
						displayMode: token.displayMode,
						throwOnError: false,
						output: "html",
					});
				} catch (err) {
					console.error("KaTeX rendering error:", err);
					return token.raw;
				}
			},
		};

		// Register extensions
		marked.use({
			extensions: [mathExtension],
		});

		// Custom code block renderer
		// Marked v18 passes an object {text, lang} instead of (code, language)
		renderer.code = (codeOrToken, languageOrUndefined) => {
			// Handle both v18 (object) and legacy (string) API
			let code, language;
			if (typeof codeOrToken === "object" && codeOrToken !== null) {
				code = codeOrToken.text || "";
				language = codeOrToken.lang || "";
			} else {
				code = codeOrToken || "";
				language = languageOrUndefined || "";
			}

			const originalLabel = language ? language.trim() : "";
			const normalizedLang = this.normalizeLanguageAlias(language);

			// Mermaid diagram detection - render as mermaid container
			if (normalizedLang === "mermaid" && this.isMermaidReady) {
				const id = `mermaid-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
				const mermaidCode = this.escapeHtml(code);
				// Mermaid copy button uses data-action for event delegation
				return `<div class="mermaid-container" data-mermaid-id="${id}">
                    <div class="code-block-header">
                        <span class="code-language">mermaid</span>
                        <button class="copy-code-btn" data-action="copy-mermaid-code" data-mermaid-code="${encodeURIComponent(code)}">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                            Copy
                        </button>
                    </div>
                    <pre class="mermaid" id="${id}">${mermaidCode}</pre>
                </div>`;
			}

			const fallbackLang = "markdown";
			let highlightLang = fallbackLang;
			// Also keep xml for html content so preview button shows
			const isHtmlContent = normalizedLang === "xml";
			if (
				normalizedLang &&
				this.isHighlightReady &&
				typeof hljs !== "undefined" &&
				hljs.getLanguage(normalizedLang)
			) {
				highlightLang = normalizedLang;
			}
			const encodedCode = encodeURIComponent(code);
			const btnRawCode = decodeURIComponent(encodedCode);
			const isHtml = isHtmlContent || this._isHtmlCode(code);
			const highlighted = this.isHighlightReady
				? hljs.highlight(code, { language: highlightLang }).value
				: this.escapeHtml(code);
			const displayLabel = originalLabel || fallbackLang;
			const previewBtn = isHtml
				? `<button class="preview-code-btn" data-action="preview-html" data-code="${encodeURIComponent(btnRawCode)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8z"/><circle cx="12" cy="12" r="3"/></svg>Preview</button>`
				: "";
			// Copy button uses data-action for event delegation
			return `<div class="code-block-container"><div class="code-block-header"><span class="code-language">${displayLabel}</span>${previewBtn}<button class="copy-code-btn" data-action="copy-code"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>Copy</button></div><pre><code class="hljs language-${highlightLang}">${highlighted}</code></pre></div>`;
		};

		// Custom image renderer to ensure images render as <img> elements
		renderer.image = (href, title, text) => {
			const {
				href: resolvedHref,
				title: resolvedTitle,
				text: resolvedText,
			} = this.resolveImageToken(href, title, text);
			const normalizedHref = this.normalizeImagePath(resolvedHref);
			const titleAttr = resolvedTitle
				? ` title="${this.escapeHtml(resolvedTitle)}"`
				: "";
			const altAttr = resolvedText
				? ` alt="${this.escapeHtml(resolvedText)}"`
				: "";
			const errorHandler = `onerror="this.onerror=null; this.outerHTML='<div class=\\'image-error\\'>⚠️ Image not found: ${this.escapeHtml(resolvedText || "Image")}</div>';"`;
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
			mangle: false,
		});
	}

	// ==================== TOOL BLOCK PRE-PARSER ====================
	/**
	 * Pre-process <tool> blocks at string level BEFORE markdown parsing.
	 * This replaces the MutationObserver approach with direct string manipulation.
	 * Handles both complete and incomplete tool blocks during streaming.
	 * @param {string} text - Raw markdown text
	 * @returns {string} Text with tool blocks converted to HTML
	 */
	preprocessToolBlocks(text) {
		if (!text) return text;
		const sourceText = typeof text === "string" ? text : String(text || "");

		// Pattern to match <tools>...</tools> blocks (including multiline)
		// Also handles unclosed <tools> tags during streaming
		const toolPattern = /<tools>([\s\S]*?)(?:<\/tools>|$)/g;

		const result = sourceText.replace(toolPattern, (_match, content) => {
			const trimmedContent = content.trim();
			if (!trimmedContent) return "";

			// Escape the content for safe display
			const escapedContent = this.escapeHtml(trimmedContent);

			// Create semantic tool result block with vertical layout
			return `<details class="system-action-block tool-result-block">
				<summary class="action-header">
					<span class="action-icon">🔧</span>
					<span class="action-label">Result / Observation</span>
				</summary>
				<div class="action-content">${escapedContent}</div>
			</details>`;
		});

		return result;
	}

	/**
	 * Preprocess <command>...</command> blocks into styled UI badges.
	 * CRITICAL: This must run BEFORE marked.js to prevent tag stripping.
	 * @param {string} text - Raw markdown text
	 * @returns {string} Text with command blocks converted to styled HTML
	 */
	preprocessCommandBlocks(text) {
		if (!text) return text;
		const sourceText = typeof text === "string" ? text : String(text || "");

		// Pattern to match <command>...</command> blocks
		const commandPattern = /<command>([\s\S]*?)<\/command>/g;

		const result = sourceText.replace(commandPattern, (_match, content) => {
			const trimmedContent = content.trim();
			if (!trimmedContent) return "";

			// Escape the command content for safe display
			const escapedContent = this.escapeHtml(trimmedContent);

			// Create semantic command block with vertical layout (no inline styles)
			return `<div class="system-action-block command-block">
				<div class="action-header">
					<span class="action-icon">⚙️</span>
					<span class="action-label">System Action</span>
				</div>
				<div class="action-content code-font">${escapedContent}</div>
			</div>`;
		});

		return result;
	}

	/**
	 * Preprocess cognitive trace blocks (<think>, <analysis>, <decision>)
	 * into collapsible <details> elements for cleaner UI.
	 * @param {string} text - Raw markdown text
	 * @returns {string} Text with cognitive blocks converted to HTML
	 */
	preprocessCognitiveBlocks(text) {
		if (!text) return text;
		const sourceText = typeof text === "string" ? text : String(text || "");

		// Cognitive block configurations
		const cognitiveBlocks = [
			{ tag: "think", label: "💭 Thinking...", icon: "💭" },
			{ tag: "analysis", label: "🔍 Analysis", icon: "🔍" },
			{ tag: "decision", label: "⚡ Decision", icon: "⚡" },
		];

		let result = sourceText;

		for (const { tag, label } of cognitiveBlocks) {
			// Pattern matches both closed tags and unclosed tags (streaming)
			// Uses [\s\S] with 's' flag equivalent for multiline matching
			const openPattern = new RegExp(`<${tag}>`, "gi");
			const closePattern = new RegExp(`</${tag}>`, "gi");

			// Count open and close tags to handle streaming edge case
			const openCount = (result.match(openPattern) || []).length;
			const closeCount = (result.match(closePattern) || []).length;

			// Full pattern for complete blocks (closed tags)
			const fullPattern = new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, "gi");

			result = result.replace(fullPattern, (_match, content) => {
				const trimmedContent = content.trim();
				if (!trimmedContent) return "";
				const escapedContent = this.escapeHtml(trimmedContent);
				return `<details class="cognitive-block cognitive-${tag}"><summary>${label}</summary><div class="cognitive-content">${escapedContent}</div></details>`;
			});

			// Handle unclosed tags during streaming (no closing tag yet)
			// This regex matches <tag> without a matching </tag>
			if (openCount > closeCount) {
				const unclosedPattern = new RegExp(`<${tag}>([\\s\\S]*?)$`, "gi");
				result = result.replace(unclosedPattern, (_match, content) => {
					const trimmedContent = content.trim();
					if (!trimmedContent) return "";
					const escapedContent = this.escapeHtml(trimmedContent);
					// Render as collapsed during streaming
					return `<details class="cognitive-block cognitive-${tag} cognitive-streaming"><summary>${label}...</summary><div class="cognitive-content">${escapedContent}</div></details>`;
				});
			}
		}

		return result;
	}

	async initializeMermaidDiagrams(container) {
		if (!this.isMermaidReady) return;

		const mermaidElements = container.querySelectorAll(
			".mermaid:not([data-processed])",
		);
		if (mermaidElements.length === 0) return;

		console.log(`Initializing ${mermaidElements.length} mermaid diagram(s)`);

		for (const el of mermaidElements) {
			try {
				await mermaid.run({ nodes: [el] });
				el.setAttribute("data-processed", "true");
			} catch (error) {
				console.error("Mermaid render error:", error);
				const errorMsg = error.message || "Unknown error";
				el.innerHTML = `<pre class="mermaid-error">Mermaid Error: ${this.escapeHtml(errorMsg)}\n\n${this.escapeHtml(el.textContent)}</pre>`;
				el.setAttribute("data-processed", "true");
			}
		}
	}

	initializeTableCopyButtons(container) {
		// Tables now use data-action attributes, no inline handlers needed
		// This method can be simplified or removed
		const tables = container.querySelectorAll("table:not([data-copy-btn])");

		tables.forEach((table) => {
			table.setAttribute("data-copy-btn", "true");

			const existingWrapper = table.closest(".table-container");
			if (existingWrapper) {
				const existingHeader = existingWrapper.querySelector(".table-header");
				if (
					existingHeader &&
					!existingHeader.querySelector(".copy-table-btn")
				) {
					const copyBtn = document.createElement("button");
					copyBtn.className = "copy-table-btn";
					copyBtn.setAttribute("data-action", "copy-table");
					copyBtn.title = "Copy table";
					copyBtn.innerHTML = `
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                        Copy
                    `;
					existingHeader.appendChild(copyBtn);
				}
			}
		});
	}

	escapeHtml(text) {
		const div = document.createElement("div");
		div.textContent = text;
		return div.innerHTML;
	}

	_isHtmlCode(code) {
		const trimmed = (code || "").trim();
		// Check for full HTML documents
		if (
			trimmed.startsWith("<!DOCTYPE") ||
			trimmed.startsWith("<html") ||
			(trimmed.startsWith("<head") && trimmed.includes("<body"))
		) {
			return true;
		}
		// Check for common HTML patterns that indicate HTML content
		const htmlPatterns = [
			/<html[\s>]/i,
			/<head[\s>]/i,
			/<body[\s>]/i,
			/<div[\s>]/i,
			/<style[\s>]/i,
			/<script[\s>]/i,
			/<link[\s]/i,
			/<meta[\s]/i,
			/<span[\s>]/i,
			/<p[\s>]/i,
			/<h[1-6][\s>]/i,
			/<img[\s]/i,
			/<a[\s]+href/i,
			/<table[\s>]/i,
			/<form[\s>]/i,
			/<input[\s]/i,
			/<button[\s>]/i,
		];
		// Return true if any HTML pattern matches
		return htmlPatterns.some((pattern) => pattern.test(trimmed));
	}

	toggleHtmlPreview(btn) {
		const rawCode = btn.getAttribute("data-code") || "";
		const code = decodeURIComponent(rawCode);
		const container = btn.closest(".code-block-container");
		if (!container) return;
		let previewWrap = container.querySelector(".html-preview-wrap");
		if (!previewWrap) {
			previewWrap = document.createElement("div");
			previewWrap.className = "html-preview-wrap hidden";
			container.appendChild(previewWrap);
		}
		if (!previewWrap.classList.contains("hidden")) {
			previewWrap.classList.add("hidden");
			btn.classList.remove("active");
			btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8z"/><circle cx="12" cy="12" r="3"/></svg>Preview`;
			return;
		}
		previewWrap.classList.remove("hidden");
		btn.classList.add("active");
		btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>Hide`;
		const sanitized = this._sanitizeHtml(code);
		const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>${this._extractInlineStyles(sanitized)}</style></head><body>${this._stripHtmlOuter(sanitized)}</body></html>`;
		let iframe = previewWrap.querySelector("iframe");
		if (!iframe) {
			iframe = document.createElement("iframe");
			iframe.className = "preview-iframe";
			iframe.setAttribute("sandbox", "allow-scripts allow-modals");
			previewWrap.appendChild(iframe);
		}
		iframe.style.display = "block";
		// Use srcdoc to bypass Android WebView cross-origin restrictions
		try {
			iframe.srcdoc = html;
		} catch (e) {
			iframe.style.display = "none";
			let err = previewWrap.querySelector(".preview-error");
			if (!err) {
				err = document.createElement("div");
				err.className = "preview-error";
				previewWrap.appendChild(err);
			}
			err.textContent = `Error: ${e.message}`;
		}
	}
	_extractInlineStyles(html) {
		const match = html.match(/<style[^>]*>([\s\S]*?)<\/style>/i);
		return match ? match[1] : "";
	}
	_stripHtmlOuter(html) {
		let previous;
		let current = html;
		do {
			previous = current;
			current = current
				.replace(/<head[^>]*>[\s\S]*?<\/head>/gi, "")
				.replace(/<!DOCTYPE[^>]*>/gi, "")
				.replace(/<html[^>]*>/gi, "")
				.replace(/<\/html>/gi, "")
				.replace(/<body[^>]*>/gi, "")
				.replace(/<\/body>/gi, "");
		} while (current !== previous);
		return current.replace(/<|>/g, "").trim();
	}
	_sanitizeHtml(html) {
		// Only strip dangerous attributes, preserve scripts (iframe is sandboxed)
		return html
			.replace(/on\w+\s*=/gi, "data-disabled-")
			.replace(/(?:javascript|data|vbscript):/gi, "");
	}

	normalizeImagePath(path) {
		if (!path) return path;
		const { href: rawPathValue } = this.resolveImageToken(path);
		let rawPath = rawPathValue;
		if (typeof rawPath !== "string") {
			rawPath = String(rawPath);
		}
		const cleaned = rawPath.trim().replace(/\\/g, "/");
		if (
			/^(https?:)?\/\//i.test(cleaned) ||
			cleaned.startsWith("data:") ||
			cleaned.startsWith("/")
		) {
			return cleaned;
		}
		if (cleaned.startsWith("static/")) {
			return `/${cleaned}`;
		}
		if (
			cleaned.startsWith("uploads/") ||
			cleaned.startsWith("generated_images/")
		) {
			return `/static/${cleaned}`;
		}
		return cleaned;
	}

	render(markdown) {
		if (markdown === null || markdown === undefined) return "";
		const safeMarkdown =
			typeof markdown === "string" ? markdown : String(markdown);

		if (!this.isMarkedReady) {
			console.warn("marked.js not ready, returning plain text");
			return this.renderWithoutMarked(safeMarkdown);
		}

		try {
			// PRE-PROCESS: Handle <command> blocks FIRST (before markdown)
			let processedMarkdown = this.preprocessCommandBlocks(safeMarkdown);

			// PRE-PROCESS: Handle <tools> blocks
			processedMarkdown = this.preprocessToolBlocks(processedMarkdown);

			// PRE-PROCESS: Handle cognitive trace blocks (think, analysis, decision)
			processedMarkdown = this.preprocessCognitiveBlocks(processedMarkdown);

			// Pre-process: Convert plain text image patterns to markdown
			processedMarkdown = this.preprocessGeneratedImages(processedMarkdown);

			// Parse markdown
			let html = marked.parse(processedMarkdown);

			// Post-process: Add table containers and callout styles
			html = this.postProcessHTML(html);

			return html;
		} catch (error) {
			console.error("Render error:", error, safeMarkdown);
			return `<pre class="render-error">${this.escapeHtml(safeMarkdown)}</pre>`;
		}
	}

	// DEPRECATED: MutationObserver removed - tool blocks are now pre-parsed
	static toolObserver = null;
	static toolObserverInitialized = false;

	// Static escape method kept for backwards compatibility
	static escapeHtmlStatic(text) {
		const div = document.createElement("div");
		div.textContent = text;
		return div.innerHTML;
	}

	// initToolObserver disabled - now handled by preprocessToolBlocks in render()
	static initToolObserver() {
		// Disabled: Tool blocks are now pre-parsed before markdown rendering
		// See preprocessToolBlocks() method
		console.log(
			"[Renderer] Tool MutationObserver disabled - using pre-parsing instead",
		);
	}

	preprocessGeneratedImages(text) {
		// Convert plain text image patterns like:
		// ! [Generated Image]
		// (static/generated_images/xxx.png)
		// These might appear on separate lines from backend output
		// Note: Backend sometimes adds space after ! like "! [text]" instead of "![text]"

		const sourceText = typeof text === "string" ? text : String(text || "");
		console.log(
			"[Renderer] Preprocessing images, input length:",
			sourceText.length,
		);

		// Single comprehensive pattern: Handle all variations
		// Matches: ! [alt] or ![alt] followed by optional whitespace/newlines then (url)
		const imagePattern = /!\s*\[([^\]]*)\]\s*\n?\s*\(([^)]+)\)/g;

		let matchCount = 0;
		let normalizedText = sourceText.replace(/\r\n/g, "\n");
		normalizedText = normalizedText.replace(imagePattern, (match, alt, src) => {
			matchCount++;
			const trimmedSrc = src.trim();
			// Encode spaces in image paths so marked.js can parse them correctly
			const encodedSrc = trimmedSrc.replace(/ /g, "%20");
			console.log(`[Renderer] Found image #${matchCount}:`, {
				alt: alt,
				src: encodedSrc,
				originalMatch:
					match.substring(0, 50) + (match.length > 50 ? "..." : ""),
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
		const temp = document.createElement("div");
		temp.innerHTML = html;

		// 1. Wrap tables in scrollable containers with header
		const tables = temp.querySelectorAll("table");
		tables.forEach((table) => {
			if (!table.parentElement.classList.contains("table-container")) {
				const wrapper = document.createElement("div");
				wrapper.className = "table-container";

				// Add header with copy button (using data-action for event delegation)
				const header = document.createElement("div");
				header.className = "table-header";
				header.innerHTML = `
                    <span class="table-label">Table</span>
                    <button class="copy-table-btn" data-action="copy-table">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                        Copy
                    </button>
                `;
				wrapper.appendChild(header);

				table.parentNode.insertBefore(wrapper, table);
				wrapper.appendChild(table);
			}
		});

		// 2. Process callout blocks (blockquotes starting with [!TYPE])
		const blockquotes = temp.querySelectorAll("blockquote");
		blockquotes.forEach((blockquote) => {
			const firstChild = blockquote.firstElementChild;
			if (firstChild?.textContent) {
				const text = firstChild.textContent.trim();
				const calloutMatch = text.match(
					/^\[!(NOTE|WARNING|INFO|TIP|IMPORTANT|CAUTION)\]/i,
				);

				if (calloutMatch) {
					const calloutType = calloutMatch[1].toLowerCase();
					blockquote.classList.add("callout", `callout-${calloutType}`);

					// Remove the [!TYPE] marker from content
					firstChild.textContent = text.replace(
						/^\[!(?:NOTE|WARNING|INFO|TIP|IMPORTANT|CAUTION)\]\s*/i,
						"",
					);
				}
			}
		});

		// 3. Apply highlight.js to any code blocks that weren't processed by marked
		if (this.isHighlightReady) {
			const codeBlocks = temp.querySelectorAll("pre code:not(.hljs)");
			codeBlocks.forEach((block) => {
				if (block.className.includes("language-")) {
					hljs.highlightElement(block);
				}
			});
		}

		return temp.innerHTML;
	}

	renderWithoutMarked(markdown) {
		try {
			let processed = this.preprocessToolBlocks(markdown);
			processed = this.preprocessGeneratedImages(processed);
			let html = this.escapeHtml(processed);

			html = html.replace(
				/!\s*\[([^\]]*)\]\s*\(([^)]+)\)/g,
				(_match, alt, src) => {
					const normalizedHref = this.normalizeImagePath(src);
					const safeAlt = this.escapeHtml(alt || "Image");
					const safeSrc = this.escapeHtml(normalizedHref);
					return `<img src="${safeSrc}" alt="${safeAlt}" class="markdown-image" loading="lazy" />`;
				},
			);

			html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
			html = html.replace(/\n/g, "<br>");

			return html;
		} catch (error) {
			console.error("Render error:", error, markdown);
			return `<pre class="render-error">${this.escapeHtml(markdown)}</pre>`;
		}
	}

	copyCode(button) {
		const codeBlock = button.closest(".code-block-container");
		const code = codeBlock?.querySelector("code")?.textContent || "";
		ClipboardUtils.copyText(code, button);
	}

	/**
	 * Copy mermaid diagram source code.
	 * Used by the copy button in mermaid code blocks.
	 */
	copyMermaidCode(button) {
		const encodedCode = button.getAttribute("data-mermaid-code") || "";
		const code = decodeURIComponent(encodedCode);
		ClipboardUtils.copyText(code, button);
	}

	renderMessage(content, _isUser = false) {
		return this.render(content);
	}

	containsImageMarkdown(content) {
		if (!content) return false;
		return /!\s*\[[^\]]*\]\s*\n?\s*\(([^)]+)\)/.test(String(content));
	}

	// ==================== STREAMING-AWARE RENDERING ====================

	/**
	 * Detects incomplete fenced code blocks using stack-based parsing
	 * @param {string} text - Raw markdown text
	 * @returns {{ hasIncomplete: boolean, incompleteBlocks: Array<{lang: string, line: number, startIndex: number}> }}
	 */
	detectIncompleteCodeBlocks(text) {
		const lines = text.split("\n");
		const stack = [];

		for (let i = 0; i < lines.length; i++) {
			const line = lines[i];
			const match = line.match(/^```(\w*)?\s*$/);

			if (!match) continue;

			// If stack has open fence, this line is a closing fence
			if (stack.length > 0) {
				stack.pop();
			} else {
				// This is an opening fence
				// Calculate startIndex in original text
				let startIndex = 0;
				for (let j = 0; j < i; j++) {
					startIndex += lines[j].length + 1; // +1 for newline
				}
				stack.push({
					lang: (match[1] || "").toLowerCase(),
					line: i,
					startIndex: startIndex,
				});
			}
		}

		return {
			hasIncomplete: stack.length > 0,
			incompleteBlocks: stack,
		};
	}

	/**
	 * Render markdown for streaming - handles incomplete mermaid blocks with placeholders
	 * @param {string} text - Accumulated stream text
	 * @param {boolean} isStreaming - Whether stream is still active
	 * @returns {string} HTML output
	 */
	/**
	 * Detects ALL mermaid blocks (complete and incomplete) in text
	 * @param {string} text - Raw markdown text
	 * @returns {Array<{startIndex: number, endIndex: number, complete: boolean}>}
	 */
	detectAllMermaidBlocks(text) {
		const blocks = [];
		const lines = text.split("\n");
		let currentBlock = null;
		let charIndex = 0;

		for (let i = 0; i < lines.length; i++) {
			const line = lines[i];
			const mermaidOpen = line.match(/^```mermaid\s*$/);

			if (mermaidOpen && !currentBlock) {
				// Start of mermaid block
				currentBlock = { startIndex: charIndex, endIndex: -1, complete: false };
			} else if (currentBlock && line.match(/^```\s*$/)) {
				// End of mermaid block (complete)
				currentBlock.endIndex = charIndex + line.length;
				currentBlock.complete = true;
				blocks.push(currentBlock);
				currentBlock = null;
			}

			charIndex += line.length + 1; // +1 for newline
		}

		// If we still have an open block, it's incomplete
		if (currentBlock) {
			currentBlock.endIndex = text.length; // End of text
			currentBlock.complete = false;
			blocks.push(currentBlock);
		}

		return blocks;
	}

	/**
	 * Render markdown for streaming - shows placeholder for ALL mermaid blocks during streaming
	 * @param {string} text - Accumulated stream text
	 * @param {boolean} isStreaming - Whether stream is still active
	 * @returns {string} HTML output
	 */
	renderStreaming(text, isStreaming = true) {
		if (!isStreaming) {
			return this.render(text); // Normal render for completed streams
		}

		// During streaming: replace ALL mermaid blocks with placeholders
		const mermaidBlocks = this.detectAllMermaidBlocks(text);

		if (mermaidBlocks.length === 0) {
			return this.render(text); // No mermaid blocks, render normally
		}

		// Replace from end to start to avoid index shifting
		let processedText = text;
		const sortedBlocks = [...mermaidBlocks].sort(
			(a, b) => b.startIndex - a.startIndex,
		);

		for (const block of sortedBlocks) {
			processedText = this._replaceMermaidWithPlaceholder(processedText, block);
		}

		return this.render(processedText);
	}

	/**
	 * Replaces any mermaid block with placeholder HTML
	 * @param {string} text - Full text
	 * @param {{startIndex: number, endIndex: number, complete: boolean}} block
	 * @returns {string} Text with placeholder
	 */
	_replaceMermaidWithPlaceholder(text, block) {
		const placeholder = `<div class="mermaid-container mermaid-placeholder">
	<div class="code-block-header">
		<span class="code-language">mermaid</span>
		<span class="mermaid-status">generating...</span>
	</div>
	<div class="mermaid-placeholder-content">
		<div class="mermaid-loader">
			<svg class="mermaid-loader-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
			</svg>
			<div class="mermaid-loader-dots">
				<span></span><span></span><span></span>
			</div>
		</div>
		<span class="mermaid-placeholder-text">Generating diagram...</span>
	</div>
</div>`;

		return (
			text.substring(0, block.startIndex) +
			placeholder +
			text.substring(block.endIndex)
		);
	}
	resolveImageToken(href, title = "", text = "") {
		if (href && typeof href === "object") {
			return {
				href: href.href || href.url || "",
				title: href.title || title || "",
				text: href.text || text || "",
			};
		}
		return { href, title, text };
	}

	showHtmlPreviewModal(btn) {
		const rawCode = decodeURIComponent(btn.dataset.code || "");
		showHtmlPreviewModal(encodeURIComponent(rawCode));
	}

	closeHtmlModal() {
		const modal = document.getElementById("html-preview-modal");
		if (modal) modal.classList.remove("active", "fullscreen");
		document.body.style.overflow = "";
	}
	togglePreviewTheme() {
		const body = document.getElementById("preview-body");
		const btn = document.getElementById("theme-toggle-btn");
		if (!body || !btn) return;
		const isLight = body.classList.toggle("preview-body-light");
		btn.classList.toggle("active", isLight);
		const iframe = document.getElementById("preview-iframe");
		if (iframe?.contentWindow) {
			iframe.contentWindow.postMessage(isLight ? "light" : "dark", "*");
		}
	}
	togglePreviewFullscreen() {
		const modal = document.getElementById("html-preview-modal");
		const btn = document.getElementById("fullscreen-toggle-btn");
		if (!modal || !btn) return;
		const isFull = modal.classList.toggle("fullscreen");
		btn.classList.toggle("active", isFull);
	}

	// Get theme variables for mermaid based on current theme
	_getMermaidThemeVariables() {
		const bodyTheme =
			document.body.getAttribute("data-theme") || "stellar-night-suisei";
		const style = getComputedStyle(document.body);
		const darkThemes = [
			"dark",
			"stellar-night-suisei",
			"tokyonight",
			"dark-lavender",
		];
		const isDark = darkThemes.includes(bodyTheme);

		return {
			darkMode: isDark,
			background: style.getPropertyValue("--code-bg").trim(),
			primaryColor: style.getPropertyValue("--accent-primary").trim(),
			primaryTextColor: style.getPropertyValue("--text-color").trim(),
			primaryBorderColor: style.getPropertyValue("--border-primary").trim(),
			lineColor: style.getPropertyValue("--border-secondary").trim(),
			secondaryColor: style.getPropertyValue("--accent-secondary").trim(),
			tertiaryColor: style.getPropertyValue("--accent-tertiary").trim(),
			edgeLabelBackground: style.getPropertyValue("--code-bg").trim(),
			nodeBorder: style.getPropertyValue("--border-primary").trim(),
			fontFamily: "JetBrains Mono, monospace",
		};
	}

	// Reinitialize mermaid when theme changes
	reinitializeMermaid() {
		if (typeof mermaid === "undefined") return;
		const themeVariables = this._getMermaidThemeVariables();
		mermaid.initialize({
			startOnLoad: false,
			theme: "base",
			themeVariables: themeVariables,
			securityLevel: "loose",
			flowchart: {
				useMaxWidth: true,
				htmlLabels: true,
				curve: "basis",
			},
			sequence: { useMaxWidth: true },
			gantt: { useMaxWidth: true },
			er: { useMaxWidth: true },
		});
		console.log("[Renderer] Mermaid reinitialized with new theme");
	}
}

// Create global renderer instance
const renderer = new MessageRenderer();

// Expose ClipboardUtils globally for use by other scripts (e.g., chat.js)
window.ClipboardUtils = ClipboardUtils;

// NOTE: Tool MutationObserver removed - tools are now pre-parsed via preprocessToolBlocks()
// Event delegation for copy buttons is handled at the top of the file (see line 68)
// === HTML Preview Modal Close Handler ===
document.addEventListener("click", (e) => {
	if (
		e.target.closest(".modal-close-btn") ||
		e.target.id === "modal-backdrop"
	) {
		renderer.closeHtmlModal();
	}
});

// === Theme Toggle for Preview ===
document.addEventListener("click", (e) => {
	if (e.target.closest("#theme-toggle-btn")) {
		renderer.togglePreviewTheme();
	}
});

// === Fullscreen Toggle for Preview ===
document.addEventListener("click", (e) => {
	if (e.target.closest("#fullscreen-toggle-btn")) {
		renderer.togglePreviewFullscreen();
	}
});
