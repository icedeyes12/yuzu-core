// FILE: static/js/renderer.js
// DESCRIPTION: Markdown renderer using marked.js with syntax highlighting
class MessageRenderer {
	constructor() {
		this.isMermaidReady = false;
		this.isMarkedReady = false;
		this.isHighlightReady = false;
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
					useMaxWidth: false,
					htmlLabels: true,
					curve: "basis",
					wrap: false,
				},
				sequence: {
					useMaxWidth: false,
					wrap: false,
				},
				gantt: {
					useMaxWidth: false,
					wrap: false,
				},
				er: {
					useMaxWidth: false,
					wrap: false,
				},
			});
			this.isMermaidReady = true;
			console.log("Mermaid initialized successfully");
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
				return `<div class="mermaid-container" data-mermaid-id="${id}">
                    <div class="code-block-header">
                        <span class="code-language">mermaid</span>
                        <button class="copy-code-btn" onclick="navigator.clipboard.writeText(decodeURIComponent('${encodeURIComponent(code)}')).then(() => { this.innerHTML='<svg width=\\'16\\' height=\\'16\\' viewBox=\\'0 0 24 24\\' fill=\\'none\\' stroke=\\'currentColor\\' stroke-width=\\'2\\'><polyline points=\\'20 6 9 17 4 12\\'></polyline></svg>Copied!'; this.classList.add('copied'); setTimeout(() => { this.innerHTML='<svg width=\\'16\\' height=\\'16\\' viewBox=\\'0 0 24 24\\' fill=\\'none\\' stroke=\\'currentColor\\' stroke-width=\\'2\\'><rect x=\\'9\\' y=\\'9\\' width=\\'13\\' height=\\'13\\' rx=\\'2\\' ry=\\'2\\'></rect><path d=\\'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\\'></path></svg>Copy'; this.classList.remove('copied'); }, 2000); })">
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
				? `<button class="preview-code-btn" data-code="${encodeURIComponent(btnRawCode)}" onclick="renderer.showHtmlPreviewModal(this)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8z"/><circle cx="12" cy="12" r="3"/></svg>Preview</button>`
				: "";
			return `<div class="code-block-container"><div class="code-block-header"><span class="code-language">${displayLabel}</span>${previewBtn}<button class="copy-code-btn" onclick="renderer.copyCode(this)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>Copy</button></div><pre><code class="hljs language-${highlightLang}">${highlighted}</code></pre></div>`;
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
		// Find all tables that don't already have a copy button
		const tables = container.querySelectorAll("table:not([data-copy-btn])");

		tables.forEach((table) => {
			// Mark as processed
			table.setAttribute("data-copy-btn", "true");

			// Create wrapper if not already wrapped
			const existingWrapper = table.closest(".table-container");
			if (existingWrapper) {
				// Already wrapped, add button to header if not present
				const existingHeader = existingWrapper.querySelector(".table-header");
				if (
					existingHeader &&
					!existingHeader.querySelector(".copy-table-btn")
				) {
					const copyBtn = document.createElement("button");
					copyBtn.className = "copy-table-btn";
					copyBtn.title = "Copy table";
					copyBtn.innerHTML = `
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                        Copy
                    `;
					copyBtn.onclick = (e) => {
						e.preventDefault();
						this.copyTable(table);
					};
					existingHeader.appendChild(copyBtn);
				}
			}
		});
	}

	copyTable(table) {
		// Convert table to TSV (tab-separated values)
		const rows = table.querySelectorAll("tr");
		const tsvLines = [];

		rows.forEach((row) => {
			const cells = row.querySelectorAll("th, td");
			const cellTexts = Array.from(cells).map((cell) => {
				// Get text content, replace newlines with spaces
				return cell.textContent.trim().replace(/\n/g, " ");
			});
			tsvLines.push(cellTexts.join("\t"));
		});

		const tsv = tsvLines.join("\n");

		navigator.clipboard
			.writeText(tsv)
			.then(() => {
				// Show success feedback
				const wrapper = table.closest(".table-container");
				if (wrapper) {
					const copyBtn = wrapper.querySelector(".copy-table-btn");
					if (copyBtn) {
						const originalHTML = copyBtn.innerHTML;
						copyBtn.innerHTML = `
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        Copied!
                    `;
						copyBtn.classList.add("copied");
						setTimeout(() => {
							copyBtn.innerHTML = originalHTML;
							copyBtn.classList.remove("copied");
						}, 2000);
					}
				}
			})
			.catch((err) => {
				console.error("Failed to copy table:", err);
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
			// Pre-process: Convert plain text image patterns to markdown
			const processedMarkdown = this.preprocessGeneratedImages(safeMarkdown);

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

				// Add header with copy button
				const header = document.createElement("div");
				header.className = "table-header";
				header.innerHTML = `
                    <span class="table-label">Table</span>
                    <button class="copy-table-btn" onclick="renderer.copyTable(this.closest('.table-container').querySelector('table'))">
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
			const processed = this.preprocessGeneratedImages(markdown);
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
		const code = codeBlock.querySelector("code").textContent;

		navigator.clipboard
			.writeText(code)
			.then(() => {
				const originalText = button.innerHTML;
				button.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                Copied!
            `;
				button.classList.add("copied");

				setTimeout(() => {
					button.innerHTML = originalText;
					button.classList.remove("copied");
				}, 2000);
			})
			.catch((err) => {
				console.error("Failed to copy code:", err);
			});
	}

	renderMessage(content, _isUser = false) {
		return this.render(content);
	}

	containsImageMarkdown(content) {
		if (!content) return false;
		return /!\s*\[[^\]]*\]\s*\n?\s*\([^)]+\)/.test(String(content));
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
		// Allow srcdoc to handle the rest (don't over-unescape)
		modal.classList.add("active");
		document.body.style.overflow = "hidden";
		// srcdoc handles HTML natively - just pass the unescaped code
		iframe.srcdoc = code;
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
			fontFamily: "inherit",
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
				useMaxWidth: false,
				htmlLabels: true,
				curve: "basis",
				wrap: false,
			},
			sequence: { useMaxWidth: false, wrap: false },
			gantt: { useMaxWidth: false, wrap: false },
			er: { useMaxWidth: false, wrap: false },
		});
		console.log("[Renderer] Mermaid reinitialized with new theme");
	}
}

// Create global renderer instance
const renderer = new MessageRenderer();

// === HTML Preview Modal ===
document.addEventListener("click", (e) => {
	var btn = e.target.closest(".preview-code-btn");
	if (!btn) return;
	var rawCode = btn.getAttribute("data-code") || "";
	try {
		rawCode = decodeURIComponent(rawCode);
	} catch (_err) {}
	if (rawCode) renderer.showHtmlPreviewModal(rawCode);
});
