# Frontend Design System Audit — Yuzu Companion

**Status:** Phase 1 complete. Audit only; no application source files were changed.
**Scope:** `static/css/**/*.css`, `static/js/**/*.js`, `templates/**/*.html`.

## Executive inventory

- CSS: **21 files** / **7,069 lines**
- JavaScript: **26 files** / **5,366 lines**
- Templates: **8 files** / **913 lines**
- CSS variable definitions: **362 declarations**, **73 unique names**
- CSS variable usages: **589 usages**, **68 unique names**
- Missing variable names found by static scan: **10**
- Hardcoded color literals/functions: **738 references**
- Duplicate selector occurrences: **229 repeated definitions** across **135 selectors**

## Frontend file map

### CSS
- `static/css/about.css` — 368 lines
- `static/css/chat.css` — 65 lines
- `static/css/components/code-blocks.css` — 62 lines
- `static/css/components/header.css` — 111 lines
- `static/css/components/html-preview.css` — 306 lines
- `static/css/components/input.css` — 98 lines
- `static/css/components/messages.css` — 528 lines
- `static/css/components/multimodal.css` — 250 lines
- `static/css/components/responsive.css` — 76 lines
- `static/css/components/scroll-button.css` — 34 lines
- `static/css/components/skeleton.css` — 113 lines
- `static/css/components/tool-cards.css` — 172 lines
- `static/css/components/typing-indicator.css` — 45 lines
- `static/css/components/utilities.css` — 121 lines
- `static/css/config.css` — 612 lines
- `static/css/home.css` — 205 lines
- `static/css/login.css` — 190 lines
- `static/css/marked.css` — 1087 lines
- `static/css/sidebar.css` — 927 lines
- `static/css/style.css` — 1018 lines
- `static/css/theme.css` — 681 lines
### JavaScript
- `static/js/about.js` — 217 lines
- `static/js/chat.js` — 178 lines
- `static/js/config.js` — 1378 lines
- `static/js/home.js` — 289 lines
- `static/js/modules/conversation-serializer.js` — 179 lines
- `static/js/modules/dom-utils.js` — 39 lines
- `static/js/modules/event-router.js` — 159 lines
- `static/js/modules/history.js` — 85 lines
- `static/js/modules/index.js` — 52 lines
- `static/js/modules/input.js` — 84 lines
- `static/js/modules/messages.js` — 210 lines
- `static/js/modules/multimodal.js` — 543 lines
- `static/js/modules/router.js` — 101 lines
- `static/js/modules/scroll.js` — 72 lines
- `static/js/modules/skeleton.js` — 40 lines
- `static/js/modules/state.js` — 34 lines
- `static/js/modules/store-renderer.js` — 240 lines
- `static/js/modules/store.js` — 191 lines
- `static/js/modules/tool-renderer/cards/generic.js` — 47 lines
- `static/js/modules/tool-renderer/cards/image.js` — 36 lines
- `static/js/modules/tool-renderer/cards/terminal.js` — 50 lines
- `static/js/modules/tool-renderer/cards/weather.js` — 68 lines
- `static/js/modules/tool-renderer/dom-utils.js` — 48 lines
- `static/js/modules/tool-renderer/index.js` — 70 lines
- `static/js/modules/tool-renderer/schemas.js` — 334 lines
- `static/js/sidebar.js` — 622 lines
### Templates
- `templates/about.html` — 169 lines
- `templates/chat.html` — 147 lines
- `templates/config.html` — 288 lines
- `templates/index.html` — 66 lines
- `templates/login.html` — 41 lines
- `templates/offline.html` — 105 lines
- `templates/partials/footer.html` — 4 lines
- `templates/sidebar.html` — 93 lines

## Token and variable audit

### Existing variable families
- `--accent*`: `--accent-color`, `--accent-highlight`, `--accent-primary`, `--accent-secondary`, `--accent-tertiary`
- `--border*`: `--border-ai`, `--border-color`, `--border-lavender`, `--border-primary`, `--border-secondary`, `--border-user`
- `--surface*`: `--surface-ai`, `--surface-base`, `--surface-elevated`, `--surface-overlay`, `--surface-user`
- `--text*`: `--text-color`, `--text-muted`, `--text-primary`, `--text-secondary`
- `--shadow*`: `--shadow-accent`, `--shadow-base`, `--shadow-secondary`, `--shadow-soft`
- `--spacing*`: `--spacing-lg`, `--spacing-md`, `--spacing-sm`, `--spacing-xl`, `--spacing-xs`
- `--radius*`: `--radius-full`, `--radius-lg`, `--radius-md`, `--radius-sm`, `--radius-xl`
- `--color*`: `--color-danger`, `--color-danger-hover`, `--color-github`, `--color-github-hover`, `--color-google`, `--color-google-hover`, `--color-info`, `--color-info-hover`, `--color-status-connected`, `--color-status-disconnected`, `--color-success`, `--color-success-hover`, `--color-warning`, `--color-warning-hover`
- `--button*`: `--button-bg`, `--button-hover`, `--button-text`
- `--message*`: `--message-ai-bg`, `--message-user-bg`
- `--bg*`: `--bg-color`, `--bg-secondary`
- `--code*`: `--code-bg`, `--code-border`
- `--tool*`: `--tool-error`, `--tool-execution-bg`, `--tool-success`
- `--backdrop*`: `--backdrop-blur`

### Variable names used but not defined in tracked CSS
- `--accent` — 2 usages
- `--accent-mint` — 3 usages
- `--bg-tertiary` — 3 usages
- `--error-color` — 2 usages
- `--font-mono` — 1 usages
- `--font-sans` — 1 usages
- `--hljs-bg` — 13 usages
- `--mono-font` — 1 usages
- `--shadow-sm` — 1 usages
- `--surface-hover` — 1 usages

### Current architecture finding
- `static/css/theme.css` already contains multiple theme blocks and legacy aliases, but the contract is mixed: semantic names, visual/hue names, component aliases, and compatibility names coexist.
- `static/css/login.css` and `static/css/config.css` introduce page-local `--color-*` variables; these are not currently part of one shared semantic contract.
- `static/css/marked.css` contains syntax-highlighting variables (`--hljs-*`) that are not defined in the tracked CSS scan.
- `static/css/home.css`, `static/css/components/*`, `static/css/sidebar.css`, and `static/css/style.css` still consume legacy aliases such as `--bg-color`, `--accent-primary`, `--border-lavender`, and `--shadow-soft`.

## Hardcoded visual values

### Hardcoded colors / color functions — 614 references
- `static/css/about.css:270` — `text-decoration-color: rgba(255, 255, 255, 0.4);`
- `static/css/about.css:278` — `background: rgba(255, 255, 255, 0.1);`
- `static/css/components/code-blocks.css:6` — `background: var(--bg-tertiary, rgba(0, 0, 0, 0.2));`
- `static/css/components/code-blocks.css:15` — `background: rgba(0, 0, 0, 0.2);`
- `static/css/components/html-preview.css:18` — `background: rgba(0, 0, 0, 0.2);`
- `static/css/components/html-preview.css:108` — `background: rgba(0, 0, 0, 0.6);`
- `static/css/components/html-preview.css:118` — `border: 1px solid var(--border-color, #333);`
- `static/css/components/html-preview.css:120` — `box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);`
- `static/css/components/html-preview.css:131` — `border-bottom: 1px solid var(--border-color, #333);`
- `static/css/components/html-preview.css:132` — `background: rgba(0, 0, 0, 0.2);`
- `static/css/components/html-preview.css:145` — `color: var(--text-secondary, #888);`
- `static/css/components/html-preview.css:154` — `color: var(--text-color, #fff);`
- `static/css/components/html-preview.css:155` — `background: rgba(255, 255, 255, 0.1);`
- `static/css/components/html-preview.css:161` — `background: #fff;`
- `static/css/components/html-preview.css:170` — `background: #fff;`
- `static/css/components/html-preview.css:181` — `border: 1px solid var(--border-color, #444);`
- `static/css/components/html-preview.css:183` — `color: var(--text-secondary, #888);`
- `static/css/components/html-preview.css:191` — `background: rgba(255, 255, 255, 0.1);`
- `static/css/components/html-preview.css:193` — `border-color: var(--text-secondary, #888);`
- `static/css/components/html-preview.css:197` — `background: rgba(255, 105, 180, 0.2);`
- `static/css/components/html-preview.css:288` — `background: rgba(210, 153, 34, 0.1);`
- `static/css/components/html-preview.css:293` — `background: rgba(248, 81, 73, 0.1);`
- `static/css/components/input.css:17` — `box-shadow: 0 -12px 32px rgba(0, 0, 0, 0.12);`
- `static/css/components/input.css:81` — `background: #dc3545;`
- `static/css/components/input.css:86` — `background: #c82333;`
- `static/css/components/input.css:93` — `box-shadow: 0 0 0 0 rgba(220, 53, 69, 0.4);`
- `static/css/components/input.css:96` — `box-shadow: 0 0 0 8px rgba(220, 53, 69, 0);`
- `static/css/components/messages.css:252` — `background: rgba(106, 169, 255, 0.08);`
- `static/css/components/messages.css:257` — `background: rgba(106, 169, 255, 0.08);`
- `static/css/components/messages.css:262` — `background: rgba(76, 175, 80, 0.08);`
- `static/css/components/messages.css:267` — `background: rgba(255, 179, 71, 0.08);`
- `static/css/components/messages.css:272` — `background: rgba(255, 107, 107, 0.08);`
- `static/css/components/messages.css:277` — `background: rgba(155, 89, 182, 0.08);`
- `static/css/components/messages.css:294` — `background: rgba(0, 0, 0, 0.2);`
- `static/css/components/messages.css:377` — `background: rgba(255, 69, 58, 0.1);`
- `static/css/components/messages.css:378` — `border: 1px solid rgba(255, 69, 58, 0.3);`
- `static/css/components/messages.css:390` — `border: 1px solid rgba(255, 69, 58, 0.3);`
- `static/css/components/messages.css:391` — `background: rgba(255, 69, 58, 0.1);`
- `static/css/components/messages.css:401` — `background: rgba(255, 255, 255, 0.03);`
- `static/css/components/messages.css:402` — `border: 1px solid var(--border-ai, rgba(255, 255, 255, 0.1));`
- `static/css/components/messages.css:409` — `border-left: 3px solid var(--accent-secondary, #8b5cf6);`
- `static/css/components/messages.css:413` — `border-left: 3px solid var(--accent-primary, #3b82f6);`
- `static/css/components/messages.css:422` — `background: rgba(0, 0, 0, 0.2);`
- `static/css/components/messages.css:424` — `color: var(--text-muted, #a1a1aa);`
- `static/css/components/messages.css:438` — `color: var(--text-color, #e2e8f0);`
- `static/css/components/messages.css:465` — `background: rgba(255, 255, 255, 0.05);`
- `static/css/components/messages.css:470` — `border-bottom: 1px solid var(--border-ai, rgba(255, 255, 255, 0.1));`
- `static/css/components/messages.css:506` — `border-left: 3px solid var(--accent, rgba(255, 255, 255, 0.3));`
- `static/css/components/messages.css:513` — `color: var(--text-muted, rgba(255, 255, 255, 0.6));`
- `static/css/components/messages.css:517` — `border-left: 3px solid var(--accent, rgba(255, 255, 255, 0.3));`
- `static/css/components/multimodal.css:73` — `box-shadow: 0 18px 38px rgba(0, 0, 0, 0.2);`
- `static/css/components/scroll-button.css:13` — `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);`
- `static/css/components/scroll-button.css:27` — `box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);`
- `static/css/components/skeleton.css:9` — `var(--surface-hover, rgba(255, 255, 255, 0.05)) 50%,`
- `static/css/components/tool-cards.css:29` — `background: rgba(0, 0, 0, 0.18);`
- `static/css/components/tool-cards.css:30` — `border: 1px solid var(--border-color, rgba(255, 255, 255, 0.1));`
- `static/css/components/tool-cards.css:40` — `color: var(--text-muted, rgba(255, 255, 255, 0.6));`
- `static/css/components/tool-cards.css:49` — `color: var(--error-color, #f87171);`
- `static/css/components/tool-cards.css:54` — `border-top: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));`
- `static/css/components/tool-cards.css:56` — `color: var(--text-muted, rgba(255, 255, 255, 0.6));`
- `static/css/components/tool-cards.css:65` — `background: rgba(255, 255, 255, 0.04);`
- `static/css/components/tool-cards.css:66` — `border: 1px solid var(--border-color, rgba(255, 255, 255, 0.1));`
- `static/css/components/tool-cards.css:89` — `color: var(--text-muted, rgba(255, 255, 255, 0.65));`
- `static/css/components/tool-cards.css:118` — `border: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));`
- `static/css/components/tool-cards.css:143` — `color: var(--text-muted, rgba(255, 255, 255, 0.6));`
- `static/css/components/tool-cards.css:150` — `background: rgba(255, 255, 255, 0.03);`
- `static/css/components/tool-cards.css:151` — `border: 1px solid var(--border-color, rgba(255, 255, 255, 0.1));`
- `static/css/components/tool-cards.css:163` — `color: var(--text-muted, rgba(255, 255, 255, 0.7));`
- `static/css/components/tool-cards.css:170` — `color: var(--error-color, #f87171);`
- `static/css/components/utilities.css:20` — `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);`
- `static/css/components/utilities.css:30` — `box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15);`
- `static/css/components/utilities.css:48` — `box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);`
- `static/css/components/utilities.css:95` — `border: 1px solid rgba(255, 69, 58, 0.3);`
- `static/css/components/utilities.css:96` — `background: rgba(255, 69, 58, 0.1);`
- `static/css/config.css:6` — `--color-warning: #f59e0b;`
- `static/css/config.css:7` — `--color-warning-hover: #d97706;`
- `static/css/config.css:8` — `--color-danger: #ef4444;`
- `static/css/config.css:9` — `--color-danger-hover: #dc2626;`
- `static/css/config.css:10` — `--color-info: #8b5cf6;`
- `static/css/config.css:11` — `--color-info-hover: #7c3aed;`
- … plus 534 more; see raw scan in the audit workspace.

### Hardcoded spacing declarations — 562 references
- `static/css/about.css:7` — `margin: 0;`
- `static/css/about.css:9` — `padding-top: 80px;`
- `static/css/about.css:10` — `padding-bottom: 60px;`
- `static/css/about.css:20` — `padding: 1.2rem 1rem;`
- `static/css/about.css:29` — `gap: 0.5rem;`
- `static/css/about.css:44` — `margin: 0;`
- `static/css/about.css:58` — `margin: 0.3rem 0 0 0;`
- `static/css/about.css:66` — `margin: 0 auto;`
- `static/css/about.css:67` — `padding: 1.5rem;`
- `static/css/about.css:74` — `margin-bottom: 2rem;`
- `static/css/about.css:75` — `padding: 2rem 1.5rem;`
- `static/css/about.css:84` — `margin: 0 0 0.8rem 0;`
- `static/css/about.css:98` — `margin: 0;`
- `static/css/about.css:104` — `padding: 1.8rem;`
- `static/css/about.css:105` — `margin-bottom: 1.5rem;`
- `static/css/about.css:118` — `margin-bottom: 1rem;`
- `static/css/about.css:123` — `margin: 0 0 1.5rem 0;`
- `static/css/about.css:131` — `margin-bottom: 1rem;`
- `static/css/about.css:141` — `padding: 1rem 1.5rem;`
- `static/css/about.css:150` — `gap: 1.5rem;`
- `static/css/about.css:151` — `margin: 2rem 0;`
- `static/css/about.css:156` — `padding: 1.5rem;`
- `static/css/about.css:160` — `gap: 1rem;`
- `static/css/about.css:182` — `margin-bottom: 0.3rem;`
- `static/css/about.css:195` — `margin: 1rem 0 0 0;`
- `static/css/about.css:199` — `padding-left: 1.5rem;`
- `static/css/about.css:200` — `margin: 1.5rem 0;`
- `static/css/about.css:204` — `margin-bottom: 0.8rem;`
- `static/css/about.css:212` — `gap: 1rem;`
- `static/css/about.css:213` — `margin: 1.5rem 0;`
- `static/css/about.css:218` — `padding: 1.2rem;`
- `static/css/about.css:232` — `margin-bottom: 0.5rem;`
- `static/css/about.css:249` — `margin: 2rem 0 0 0;`
- `static/css/about.css:250` — `padding-top: 1rem;`
- `static/css/about.css:261` — `padding: 1rem;`
- `static/css/about.css:273` — `padding: 2px 6px;`
- `static/css/about.css:322` — `padding-top: 70px;`
- `static/css/about.css:323` — `padding-bottom: 50px;`
- `static/css/about.css:327` — `padding: 1rem;`
- `static/css/about.css:339` — `padding: 1.2rem;`
- `static/css/chat.css:21` — `margin: 0;`
- `static/css/chat.css:22` — `padding: 0;`
- `static/css/chat.css:41` — `padding-top: 76px;`
- `static/css/chat.css:42` — `padding-bottom: 8rem;`
- `static/css/chat.css:50` — `padding-bottom: max(0.8rem, env(safe-area-inset-bottom));`
- `static/css/components/code-blocks.css:3` — `margin: 1rem 0;`
- `static/css/components/code-blocks.css:14` — `padding: 0.5rem 1rem;`
- `static/css/components/code-blocks.css:29` — `gap: 0.3rem;`
- `static/css/components/code-blocks.css:33` — `padding: 0.3rem 0.6rem;`
- `static/css/components/code-blocks.css:52` — `margin: 0;`
- `static/css/components/code-blocks.css:53` — `padding: 1rem;`
- `static/css/components/header.css:14` — `gap: 0.75rem;`
- `static/css/components/header.css:15` — `padding: max(0.65rem, env(safe-area-inset-top))`
- `static/css/components/header.css:26` — `gap: 0.5rem;`
- `static/css/components/header.css:38` — `padding: 0;`
- `static/css/components/header.css:39` — `margin-right: 0.5rem;`
- `static/css/components/header.css:57` — `gap: 0.2rem;`
- `static/css/components/header.css:69` — `margin: 0;`
- `static/css/components/header.css:87` — `gap: 0.5rem;`
- `static/css/components/html-preview.css:6` — `margin: 1rem 0;`
- `static/css/components/html-preview.css:17` — `padding: 0.5rem 1rem;`
- `static/css/components/html-preview.css:29` — `gap: 0.4rem;`
- `static/css/components/html-preview.css:40` — `gap: 0.3rem;`
- `static/css/components/html-preview.css:41` — `padding: 0.3rem 0.7rem;`
- `static/css/components/html-preview.css:79` — `padding: 1rem 1rem 0.8rem;`
- `static/css/components/html-preview.css:86` — `padding: 1rem;`
- `static/css/components/html-preview.css:130` — `padding: 12px 16px;`
- `static/css/components/html-preview.css:147` — `padding: 4px;`
- `static/css/components/html-preview.css:176` — `gap: 4px;`
- `static/css/components/html-preview.css:185` — `padding: 5px 7px;`
- `static/css/components/html-preview.css:209` — `margin: 0;`
- `static/css/components/html-preview.css:246` — `padding: 4px 8px;`
- `static/css/components/html-preview.css:267` — `padding: 2px 6px;`
- `static/css/components/html-preview.css:277` — `padding: 2px 8px;`
- `static/css/components/html-preview.css:301` — `padding: 8px;`
- `static/css/components/input.css:13` — `gap: 0.5rem;`
- `static/css/components/input.css:14` — `padding: 0.75rem max(1rem, calc((100vw - 900px) / 2));`
- `static/css/components/input.css:15` — `padding-bottom: max(0.75rem, env(safe-area-inset-bottom));`
- `static/css/components/input.css:26` — `padding: 0.7rem 1rem;`
- `static/css/components/input.css:65` — `margin-right: 2px;`
- … plus 482 more; see raw scan in the audit workspace.

### Hardcoded radius declarations — 154 references
- `static/css/about.css:77` — `border-radius: 1.5rem;`
- `static/css/about.css:103` — `border-radius: 1.2rem;`
- `static/css/about.css:142` — `border-radius: 1rem;`
- `static/css/about.css:157` — `border-radius: 1rem;`
- `static/css/about.css:219` — `border-radius: 0.8rem;`
- `static/css/about.css:274` — `border-radius: 4px;`
- `static/css/components/code-blocks.css:4` — `border-radius: 8px;`
- `static/css/components/code-blocks.css:32` — `border-radius: 4px;`
- `static/css/components/header.css:51` — `border-radius: 10px;`
- `static/css/components/header.css:102` — `border-radius: 10px;`
- `static/css/components/header.css:109` — `border-radius: 10px;`
- `static/css/components/html-preview.css:8` — `border-radius: 8px;`
- `static/css/components/html-preview.css:45` — `border-radius: 6px;`
- `static/css/components/html-preview.css:71` — `border-radius: 0 0 8px 8px;`
- `static/css/components/html-preview.css:119` — `border-radius: 12px;`
- `static/css/components/html-preview.css:148` — `border-radius: 4px;`
- `static/css/components/html-preview.css:182` — `border-radius: 6px;`
- `static/css/components/html-preview.css:208` — `border-radius: 0;`
- `static/css/components/html-preview.css:268` — `border-radius: 4px;`
- `static/css/components/input.css:28` — `border-radius: 20px;`
- `static/css/components/input.css:45` — `border-radius: 50%;`
- `static/css/components/messages.css:58` — `border-radius: 1.2rem;`
- `static/css/components/messages.css:85` — `border-radius: 12px;`
- `static/css/components/messages.css:107` — `border-radius: 8px;`
- `static/css/components/messages.css:161` — `border-radius: 6px;`
- `static/css/components/messages.css:237` — `border-radius: 4px;`
- `static/css/components/messages.css:245` — `border-radius: 6px;`
- `static/css/components/messages.css:284` — `border-radius: 6px;`
- `static/css/components/messages.css:311` — `border-radius: 4px;`
- `static/css/components/messages.css:333` — `border-radius: 0;`
- `static/css/components/messages.css:354` — `border-radius: 6px;`
- `static/css/components/messages.css:368` — `border-radius: 8px;`
- `static/css/components/messages.css:376` — `border-radius: 8px;`
- `static/css/components/messages.css:389` — `border-radius: 8px;`
- `static/css/components/messages.css:403` — `border-radius: 12px;`
- `static/css/components/messages.css:484` — `border-radius: 4px;`
- `static/css/components/multimodal.css:12` — `border-radius: 50%;`
- `static/css/components/multimodal.css:36` — `border-radius: 50%;`
- `static/css/components/multimodal.css:53` — `border-radius: 50%;`
- `static/css/components/multimodal.css:75` — `border-radius: 12px;`
- `static/css/components/multimodal.css:85` — `border-radius: 8px;`
- `static/css/components/multimodal.css:145` — `border-radius: 8px;`
- `static/css/components/multimodal.css:187` — `border-radius: 6px;`
- `static/css/components/multimodal.css:200` — `border-radius: 50%;`
- `static/css/components/multimodal.css:218` — `border-radius: 8px;`
- `static/css/components/multimodal.css:235` — `border-radius: 6px;`
- `static/css/components/scroll-button.css:8` — `border-radius: 50%;`
- `static/css/components/skeleton.css:14` — `border-radius: var(--radius-md, 8px);`
- `static/css/components/skeleton.css:32` — `border-radius: 12px;`
- `static/css/components/skeleton.css:47` — `border-radius: 50%;`
- `static/css/components/skeleton.css:52` — `border-radius: var(--radius-sm, 4px);`
- `static/css/components/skeleton.css:73` — `border-radius: var(--radius-md, 8px);`
- `static/css/components/skeleton.css:81` — `border-radius: var(--radius-sm, 4px);`
- `static/css/components/skeleton.css:87` — `border-radius: var(--radius-sm, 4px);`
- `static/css/components/skeleton.css:93` — `border-radius: var(--radius-sm, 4px);`
- `static/css/components/skeleton.css:99` — `border-radius: var(--radius-md, 8px);`
- `static/css/components/skeleton.css:105` — `border-radius: var(--radius-md, 8px);`
- `static/css/components/skeleton.css:112` — `border-radius: var(--radius-sm, 4px);`
- `static/css/components/tool-cards.css:31` — `border-radius: 6px;`
- `static/css/components/tool-cards.css:67` — `border-radius: 10px;`
- `static/css/components/tool-cards.css:119` — `border-radius: 7px;`
- `static/css/components/tool-cards.css:139` — `border-radius: 6px;`
- `static/css/components/tool-cards.css:152` — `border-radius: 6px;`
- `static/css/components/typing-indicator.css:15` — `border-radius: 1rem;`
- `static/css/components/typing-indicator.css:22` — `border-radius: 50%;`
- `static/css/components/utilities.css:94` — `border-radius: 8px;`
- `static/css/config.css:84` — `border-radius: 0.8rem;`
- `static/css/config.css:131` — `border-radius: 8px;`
- `static/css/config.css:168` — `border-radius: 3px;`
- `static/css/config.css:178` — `border-radius: 50%;`
- `static/css/config.css:188` — `border-radius: 50%;`
- `static/css/config.css:198` — `border-radius: 8px;`
- `static/css/config.css:266` — `border-radius: 8px;`
- `static/css/config.css:302` — `border-radius: 6px;`
- `static/css/config.css:337` — `border-radius: 8px;`
- `static/css/config.css:381` — `border-radius: 8px;`
- `static/css/config.css:412` — `border-radius: 12px;`
- `static/css/config.css:444` — `border-radius: 999px;`
- `static/css/config.css:466` — `border-radius: 12px;`
- `static/css/config.css:572` — `border-radius: 6px;`
- … plus 74 more; see raw scan in the audit workspace.

### Hardcoded shadows — 50 references
- `static/css/about.css:79` — `box-shadow: var(--shadow-soft);`
- `static/css/about.css:107` — `box-shadow: var(--shadow-soft);`
- `static/css/about.css:113` — `box-shadow: 0 10px 25px var(--shadow-accent);`
- `static/css/about.css:227` — `box-shadow: 0 5px 15px var(--shadow-accent);`
- `static/css/components/html-preview.css:120` — `box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);`
- `static/css/components/input.css:17` — `box-shadow: 0 -12px 32px rgba(0, 0, 0, 0.12);`
- `static/css/components/input.css:58` — `box-shadow: 0 4px 12px var(--shadow-accent);`
- `static/css/components/input.css:71` — `box-shadow: 0 6px 16px var(--shadow-accent);`
- `static/css/components/input.css:93` — `box-shadow: 0 0 0 0 rgba(220, 53, 69, 0.4);`
- `static/css/components/input.css:96` — `box-shadow: 0 0 0 8px rgba(220, 53, 69, 0);`
- `static/css/components/messages.css:61` — `box-shadow: var(--shadow-sm);`
- `static/css/components/multimodal.css:73` — `box-shadow: 0 18px 38px rgba(0, 0, 0, 0.2);`
- `static/css/components/scroll-button.css:13` — `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);`
- `static/css/components/scroll-button.css:27` — `box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);`
- `static/css/components/utilities.css:20` — `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);`
- `static/css/components/utilities.css:30` — `box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15);`
- `static/css/components/utilities.css:48` — `box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);`
- `static/css/config.css:89` — `box-shadow: var(--shadow-soft);`
- `static/css/config.css:95` — `box-shadow: 0 8px 25px var(--shadow-accent);`
- `static/css/config.css:144` — `box-shadow: 0 0 0 3px var(--shadow-accent);`
- `static/css/config.css:182` — `box-shadow: 0 2px 6px var(--shadow-accent);`
- `static/css/config.css:192` — `box-shadow: 0 2px 6px var(--shadow-accent);`
- `static/css/config.css:211` — `box-shadow: 0 3px 12px var(--shadow-accent);`
- `static/css/config.css:217` — `box-shadow: 0 5px 15px var(--shadow-accent);`
- `static/css/config.css:390` — `box-shadow: 0 4px 15px var(--shadow-accent);`
- `static/css/config.css:404` — `box-shadow: 0 0 10px rgba(16, 185, 129, 0.2);`
- `static/css/home.css:71` — `box-shadow: var(--shadow-soft);`
- `static/css/home.css:77` — `box-shadow: 0 10px 30px var(--shadow-accent);`
- `static/css/home.css:185` — `box-shadow: var(--shadow-soft);`
- `static/css/login.css:44` — `box-shadow: var(--shadow-soft);`
- `static/css/login.css:76` — `box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);`
- `static/css/login.css:149` — `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);`
- `static/css/login.css:160` — `box-shadow: var(--shadow-soft);`
- `static/css/marked.css:311` — `box-shadow: var(--shadow-soft);`
- `static/css/sidebar.css:16` — `box-shadow: 18px 0 48px rgba(0, 0, 0, 0.22);`
- `static/css/sidebar.css:184` — `box-shadow: 0 4px 20px var(--shadow-base);`
- `static/css/sidebar.css:400` — `box-shadow: 0 4px 20px var(--shadow-base);`
- `static/css/sidebar.css:479` — `box-shadow: 0 2px 8px var(--shadow-base);`
- `static/css/sidebar.css:838` — `box-shadow: var(--shadow-base);`
- `static/css/style.css:132` — `box-shadow: 0 4px 15px var(--shadow-accent);`
- `static/css/style.css:137` — `box-shadow: 0 6px 20px var(--shadow-accent);`
- `static/css/style.css:193` — `box-shadow: 0 0 0 3px var(--shadow-accent);`
- `static/css/style.css:217` — `box-shadow: var(--shadow-soft);`
- `static/css/style.css:223` — `box-shadow: 0 10px 30px var(--shadow-accent);`
- `static/css/style.css:607` — `box-shadow: var(--shadow-soft);`
- `static/css/style.css:610` — `box-shadow: 0 10px 30px var(--shadow-base);`
- `static/css/style.css:613` — `box-shadow: none;`
- `static/css/style.css:716` — `box-shadow: none;`
- `static/js/about.js:184` — `box-shadow: 0 10px 30px var(--shadow-pink);`
- `static/js/config.js:1022` — `box-shadow: var(--shadow-soft);`

### Transitions — 30 references
- `static/css/components/header.css:110` — `transition: width 0.3s ease;`
- `static/css/components/input.css:59` — `transition:`
- `static/css/components/scroll-button.css:17` — `transition:`
- `static/css/components/utilities.css:10` — `transition:`
- `static/css/components/utilities.css:24` — `transition:`
- `static/css/components/utilities.css:34` — `transition:`
- `static/css/components/utilities.css:40` — `transition:`
- `static/css/components/utilities.css:53` — `transition: background-color 0.2s ease;`
- `static/css/components/utilities.css:58` — `transition:`
- `static/css/components/utilities.css:66` — `transition:`
- `static/css/components/utilities.css:72` — `transition:`
- `static/css/components/utilities.css:84` — `transition:`
- `static/css/components/utilities.css:114` — `transition-duration: 0.01ms;`
- `static/css/config.css:543` — `transition:`
- `static/css/home.css:197` — `transition:`
- `static/css/login.css:138` — `transition:`
- `static/css/marked.css:1021` — `transition: background 0.2s ease;`
- `static/css/marked.css:1044` — `transition: transform 0.2s ease;`
- `static/css/sidebar.css:12` — `transition: left 0.3s ease;`
- `static/css/sidebar.css:70` — `transition: opacity 0.2s;`
- `static/css/sidebar.css:162` — `transition: transform 0.3s ease;`
- `static/css/sidebar.css:347` — `transition: opacity 0.2s ease;`
- `static/css/sidebar.css:743` — `transition:`
- `static/css/style.css:13` — `transition: opacity 0.18s ease;`
- `static/css/style.css:89` — `transition:`
- `static/css/style.css:111` — `transition:`
- `static/css/style.css:735` — `transition-duration: 0.01ms;`
- `static/css/theme.css:589` — `transition:`
- `static/css/theme.css:595` — `transition:`
- `templates/offline.html:70` — `transition: all 0.3s ease;`

### Z-index declarations — 23 references
- `static/css/about.css:18` — `z-index: 90;`
- `static/css/about.css:69` — `z-index: 1;`
- `static/css/about.css:259` — `z-index: 90;`
- `static/css/chat.css:57` — `z-index: 40;`
- `static/css/components/header.css:10` — `z-index: 100;`
- `static/css/components/html-preview.css:96` — `z-index: 9999;`
- `static/css/components/input.css:10` — `z-index: 100;`
- `static/css/components/multimodal.css:77` — `z-index: 1000;`
- `static/css/components/scroll-button.css:5` — `z-index: 1000;`
- `static/css/config.css:31` — `z-index: 90;`
- `static/css/config.css:73` — `z-index: 1;`
- `static/css/config.css:590` — `z-index: 90;`
- `static/css/home.css:103` — `z-index: 90;`
- `static/css/login.css:78` — `z-index: 10;`
- `static/css/login.css:95` — `z-index: 0;`
- `static/css/sidebar.css:11` — `z-index: 10001;`
- `static/css/sidebar.css:31` — `z-index: 10000;`
- `static/css/sidebar.css:183` — `z-index: 10002;`
- `static/css/sidebar.css:395` — `z-index: 10000;`
- `static/css/sidebar.css:822` — `z-index: 10002;`
- `static/js/about.js:185` — `z-index: 10000;`
- `static/js/config.js:1023` — `z-index: 10000;`
- `static/js/home.js:220` — `z-index: -1;`

### Opacity declarations — 72 references
- `static/css/about.css:97` — `opacity: 0.9;`
- `static/css/about.css:132` — `opacity: 0.9;`
- `static/css/about.css:188` — `opacity: 0.8;`
- `static/css/about.css:194` — `opacity: 0.7;`
- `static/css/about.css:206` — `opacity: 0.9;`
- `static/css/about.css:239` — `opacity: 0.8;`
- `static/css/about.css:248` — `opacity: 0.8;`
- `static/css/about.css:284` — `opacity: 0;`
- `static/css/about.css:291` — `opacity: 1;`
- `static/css/components/input.css:75` — `opacity: 0.6;`
- `static/css/components/messages.css:35` — `opacity: 0;`
- `static/css/components/messages.css:39` — `opacity: 1;`
- `static/css/components/messages.css:100` — `opacity: 0.8;`
- `static/css/components/messages.css:133` — `opacity: 0.7;`
- `static/css/components/messages.css:164` — `opacity: 0.7;`
- `static/css/components/messages.css:172` — `opacity: 1;`
- `static/css/components/messages.css:487` — `opacity: 0.9;`
- `static/css/components/messages.css:508` — `opacity: 0.85;`
- `static/css/components/multimodal.css:118` — `opacity: 0.7;`
- `static/css/components/scroll-button.css:31` — `opacity: 0;`
- `static/css/components/typing-indicator.css:8` — `opacity: 0.7;`
- `static/css/components/typing-indicator.css:39` — `opacity: 0.5;`
- `static/css/components/typing-indicator.css:43` — `opacity: 1;`
- `static/css/config.css:342` — `opacity: 0.55;`
- `static/css/home.css:196` — `opacity: 0.9;`
- `static/css/login.css:92` — `opacity: 0.5;`
- `static/css/marked.css:151` — `opacity: 0.9;`
- `static/css/marked.css:442` — `opacity: 0.7;`
- `static/css/marked.css:469` — `opacity: 0.6;`
- `static/css/marked.css:566` — `opacity: 0.7;`
- `static/css/marked.css:612` — `opacity: 0.6;`
- `static/css/marked.css:680` — `opacity: 1;`
- `static/css/marked.css:684` — `opacity: 0;`
- `static/css/marked.css:868` — `opacity: 0.8;`
- `static/css/marked.css:897` — `opacity: 0.4;`
- `static/css/marked.css:900` — `opacity: 1;`
- `static/css/sidebar.css:69` — `opacity: 0.7;`
- `static/css/sidebar.css:74` — `opacity: 1;`
- `static/css/sidebar.css:181` — `opacity: 0;`
- `static/css/sidebar.css:189` — `opacity: 1;`
- `static/css/sidebar.css:311` — `opacity: 0.6;`
- `static/css/sidebar.css:316` — `opacity: 0.5;`
- `static/css/sidebar.css:339` — `opacity: 0.8;`
- `static/css/sidebar.css:346` — `opacity: 0;`
- `static/css/sidebar.css:353` — `opacity: 1;`
- `static/css/sidebar.css:433` — `opacity: 0;`
- `static/css/sidebar.css:437` — `opacity: 1;`
- `static/css/sidebar.css:511` — `opacity: 1; /* Always show on mobile for better UX */`
- `static/css/sidebar.css:805` — `opacity: 0.6;`
- `static/css/style.css:17` — `opacity: 0;`
- `static/css/style.css:23` — `opacity: 0.45;`
- `static/css/style.css:617` — `opacity: 0;`
- `static/css/style.css:620` — `opacity: 0.25;`
- `static/css/style.css:623` — `opacity: 0.5;`
- `static/css/style.css:626` — `opacity: 0.75;`
- `static/css/style.css:629` — `opacity: 1;`
- `static/css/style.css:678` — `opacity: 0.6;`
- `static/css/style.css:774` — `opacity: 0;`
- `static/css/style.css:777` — `opacity: 1;`
- `static/css/style.css:783` — `opacity: 0;`
- `static/css/style.css:787` — `opacity: 1;`
- `static/css/style.css:794` — `opacity: 0;`
- `static/css/style.css:798` — `opacity: 1;`
- `static/css/style.css:805` — `opacity: 0;`
- `static/css/style.css:809` — `opacity: 1;`
- `static/css/style.css:816` — `opacity: 0;`
- `static/css/style.css:820` — `opacity: 1;`
- `static/css/style.css:827` — `opacity: 1;`
- `static/js/home.js:226` — `opacity: 0;`
- `static/js/home.js:236` — `opacity: 0;`
- `static/js/home.js:240` — `opacity: 1;`
- `static/js/home.js:253` — `opacity: 0.7;`

### Font sizes — 196 references
- `static/css/about.css:45` — `font-size: 1.8rem;`
- `static/css/about.css:61` — `font-size: 0.9rem;`
- `static/css/about.css:83` — `font-size: 2.2rem;`
- `static/css/about.css:96` — `font-size: 1.1rem;`
- `static/css/about.css:117` — `font-size: 2rem;`
- `static/css/about.css:124` — `font-size: 1.8rem;`
- `static/css/about.css:171` — `font-size: 2rem;`
- `static/css/about.css:181` — `font-size: 1.1rem;`
- `static/css/about.css:187` — `font-size: 0.9rem;`
- `static/css/about.css:233` — `font-size: 1rem;`
- `static/css/about.css:238` — `font-size: 0.85rem;`
- `static/css/about.css:331` — `font-size: 1.8rem;`
- `static/css/about.css:335` — `font-size: 1rem;`
- `static/css/about.css:351` — `font-size: 1.5rem;`
- `static/css/about.css:355` — `font-size: 1.5rem;`
- `static/css/components/code-blocks.css:20` — `font-size: 0.75rem;`
- `static/css/components/code-blocks.css:34` — `font-size: 0.75rem;`
- `static/css/components/code-blocks.css:60` — `font-size: 0.9rem;`
- `static/css/components/header.css:66` — `font-size: 1.1rem;`
- `static/css/components/header.css:76` — `font-size: 0.75rem;`
- `static/css/components/html-preview.css:23` — `font-size: 0.75rem;`
- `static/css/components/html-preview.css:46` — `font-size: 0.8rem;`
- `static/css/components/html-preview.css:81` — `font-size: 0.85rem;`
- `static/css/components/html-preview.css:88` — `font-size: 0.85rem;`
- `static/css/components/html-preview.css:137` — `font-size: 0.85rem;`
- `static/css/components/html-preview.css:232` — `font-size: 11px;`
- `static/css/components/html-preview.css:254` — `font-size: 10px;`
- `static/css/components/html-preview.css:266` — `font-size: 10px;`
- `static/css/components/html-preview.css:305` — `font-size: 11px;`
- `static/css/components/input.css:31` — `font-size: 0.95rem;`
- `static/css/components/messages.css:110` — `font-size: 0.85rem;`
- `static/css/components/messages.css:115` — `font-size: 0.75rem;`
- `static/css/components/messages.css:127` — `font-size: 0.95rem;`
- `static/css/components/messages.css:131` — `font-size: 0.7rem;`
- `static/css/components/messages.css:200` — `font-size: 1.8rem;`
- `static/css/components/messages.css:203` — `font-size: 1.5rem;`
- `static/css/components/messages.css:206` — `font-size: 1.3rem;`
- `static/css/components/messages.css:209` — `font-size: 1.1rem;`
- `static/css/components/messages.css:212` — `font-size: 1rem;`
- `static/css/components/messages.css:215` — `font-size: 0.9rem;`
- `static/css/components/messages.css:299` — `font-size: 0.75rem;`
- `static/css/components/messages.css:313` — `font-size: 0.75rem;`
- `static/css/components/messages.css:380` — `font-size: 0.9rem;`
- `static/css/components/messages.css:423` — `font-size: 0.8rem;`
- `static/css/components/messages.css:435` — `font-size: 0.85rem;`
- `static/css/components/messages.css:486` — `font-size: 0.85rem;`
- `static/css/components/messages.css:512` — `font-size: 0.85em;`
- `static/css/components/messages.css:522` — `font-size: 0.85em;`
- `static/css/components/multimodal.css:37` — `font-size: 0.7rem;`
- `static/css/components/multimodal.css:54` — `font-size: 0.7rem;`
- `static/css/components/multimodal.css:113` — `font-size: 0.95rem;`
- `static/css/components/multimodal.css:117` — `font-size: 0.75rem;`
- `static/css/components/multimodal.css:130` — `font-size: 0.85rem;`
- `static/css/components/multimodal.css:163` — `font-size: 0.75rem;`
- `static/css/components/multimodal.css:237` — `font-size: 0.85rem;`
- `static/css/components/multimodal.css:248` — `font-size: 0.9rem;`
- `static/css/components/responsive.css:42` — `font-size: 0.85rem;`
- `static/css/components/responsive.css:52` — `font-size: 1rem;`
- `static/css/components/responsive.css:56` — `font-size: 0.7rem;`
- `static/css/components/tool-cards.css:28` — `font-size: 0.85em;`
- `static/css/components/tool-cards.css:37` — `font-size: 0.7em;`
- `static/css/components/tool-cards.css:55` — `font-size: 0.75em;`
- `static/css/components/tool-cards.css:88` — `font-size: 0.8em;`
- `static/css/components/tool-cards.css:92` — `font-size: 2.2em;`
- `static/css/components/tool-cards.css:96` — `font-size: 1.8em;`
- `static/css/components/tool-cards.css:107` — `font-size: 0.9em;`
- `static/css/components/tool-cards.css:124` — `font-size: 0.8em;`
- `static/css/components/tool-cards.css:127` — `font-size: 1.5em;`
- `static/css/components/tool-cards.css:142` — `font-size: 0.75em;`
- `static/css/components/tool-cards.css:171` — `font-size: 0.85em;`
- `static/css/config.css:58` — `font-size: 1.5rem;`
- `static/css/config.css:67` — `font-size: 0.9rem;`
- `static/css/config.css:100` — `font-size: 1.2rem;`
- `static/css/config.css:122` — `font-size: 0.9rem;`
- `static/css/config.css:134` — `font-size: 0.9rem;`
- `static/css/config.css:203` — `font-size: 0.9rem;`
- `static/css/config.css:268` — `font-size: 0.9rem;`
- `static/css/config.css:300` — `font-size: 0.85rem;`
- `static/css/config.css:316` — `font-size: 0.8rem;`
- `static/css/config.css:395` — `font-size: 1.05rem;`
- … plus 116 more; see raw scan in the audit workspace.

### Line heights — 15 references
- `static/css/about.css:130` — `line-height: 1.7;`
- `static/css/about.css:205` — `line-height: 1.6;`
- `static/css/components/code-blocks.css:61` — `line-height: 1.5;`
- `static/css/components/html-preview.css:233` — `line-height: 1.5;`
- `static/css/components/messages.css:126` — `line-height: 1.6;`
- `static/css/components/messages.css:439` — `line-height: 1.5;`
- `static/css/components/tool-cards.css:93` — `line-height: 1;`
- `static/css/config.css:454` — `line-height: 1.5;`
- `static/css/marked.css:394` — `line-height: 1.5;`
- `static/css/marked.css:967` — `line-height: 1.5;`
- `static/css/marked.css:1063` — `line-height: 1.5;`
- `static/css/style.css:44` — `line-height: 1.6;`
- `static/css/style.css:57` — `line-height: 1.3;`
- `static/css/style.css:83` — `line-height: 1.6;`
- `templates/offline.html:43` — `line-height: 1.6;`

## Duplicate CSS and utility patterns

### `0%` — 8 definitions
- `static/css/components/input.css:90`
- `static/css/components/skeleton.css:17`
- `static/css/components/typing-indicator.css:34`
- `static/css/login.css:112`
- `static/css/marked.css:677`
- `static/css/marked.css:894`
- `static/css/style.css:814`
- `static/css/style.css:832`

### `100%` — 8 definitions
- `static/css/components/input.css:90`
- `static/css/components/skeleton.css:20`
- `static/css/components/typing-indicator.css:34`
- `static/css/login.css:121`
- `static/css/marked.css:681`
- `static/css/marked.css:894`
- `static/css/style.css:825`
- `static/css/style.css:835`

### `.card` — 7 definitions
- `static/css/components/utilities.css:75`
- `static/css/home.css:60`
- `static/css/home.css:141`
- `static/css/home.css:155`
- `static/css/style.css:712`
- `static/css/style.css:883`
- `static/css/style.css:909`

### `to` — 7 definitions
- `static/css/about.css:289`
- `static/css/components/messages.css:37`
- `static/css/sidebar.css:434`
- `static/css/style.css:775`
- `static/css/style.css:785`
- `static/css/style.css:796`
- `static/css/style.css:807`

### `from` — 6 definitions
- `static/css/components/messages.css:33`
- `static/css/sidebar.css:430`
- `static/css/style.css:772`
- `static/css/style.css:781`
- `static/css/style.css:792`
- `static/css/style.css:803`

### `.hamburger-menu` — 5 definitions
- `static/css/components/header.css:27`
- `static/css/components/responsive.css:62`
- `static/css/sidebar.css:530`
- `static/css/sidebar.css:614`
- `static/css/sidebar.css:658`

### `.hamburger-menu span` — 5 definitions
- `static/css/components/header.css:45`
- `static/css/sidebar.css:480`
- `static/css/sidebar.css:535`
- `static/css/sidebar.css:619`
- `static/css/sidebar.css:663`

### `.container` — 4 definitions
- `static/css/style.css:842`
- `static/css/style.css:848`
- `static/css/style.css:864`
- `static/css/style.css:890`

### `.dropdown-option` — 4 definitions
- `static/css/components/utilities.css:62`
- `static/css/sidebar.css:192`
- `static/css/sidebar.css:539`
- `static/css/sidebar.css:690`

### `.dropdown-selected` — 4 definitions
- `static/css/components/utilities.css:62`
- `static/css/sidebar.css:135`
- `static/css/sidebar.css:539`
- `static/css/sidebar.css:690`

### `.form-select` — 4 definitions
- `static/css/config.css:123`
- `static/css/config.css:520`
- `static/css/style.css:173`
- `static/css/style.css:199`

### `.hamburger` — 4 definitions
- `static/css/about.css:30`
- `static/css/components/header.css:40`
- `static/css/config.css:43`
- `static/css/home.css:20`

### `.header-content` — 4 definitions
- `static/css/about.css:24`
- `static/css/components/header.css:21`
- `static/css/config.css:37`
- `static/css/home.css:14`

### `.header-title` — 4 definitions
- `static/css/about.css:35`
- `static/css/components/header.css:58`
- `static/css/config.css:48`
- `static/css/home.css:25`

### `.message-content h1` — 4 definitions
- `static/css/components/messages.css:197`
- `static/css/marked.css:24`
- `static/css/marked.css:43`
- `static/css/marked.css:50`

### `.message-content h2` — 4 definitions
- `static/css/components/messages.css:201`
- `static/css/marked.css:28`
- `static/css/marked.css:43`
- `static/css/marked.css:54`

### `.message-content h3` — 4 definitions
- `static/css/components/messages.css:204`
- `static/css/marked.css:31`
- `static/css/marked.css:43`
- `static/css/marked.css:57`

### `.message-content th` — 4 definitions
- `static/css/components/messages.css:336`
- `static/css/components/messages.css:343`
- `static/css/marked.css:227`
- `static/css/marked.css:234`

### `.sidebar-header` — 4 definitions
- `static/css/sidebar.css:38`
- `static/css/sidebar.css:551`
- `static/css/sidebar.css:623`
- `static/css/sidebar.css:668`

### `.sidebar-header h2` — 4 definitions
- `static/css/sidebar.css:48`
- `static/css/sidebar.css:555`
- `static/css/sidebar.css:627`
- `static/css/sidebar.css:672`

### `.sidebar-link` — 4 definitions
- `static/css/components/utilities.css:54`
- `static/css/sidebar.css:95`
- `static/css/sidebar.css:567`
- `static/css/sidebar.css:640`

### `50%` — 4 definitions
- `static/css/components/input.css:94`
- `static/css/marked.css:677`
- `static/css/marked.css:898`
- `static/css/style.css:818`

### `body` — 4 definitions
- `static/css/chat.css:25`
- `static/css/components/utilities.css:69`
- `static/css/style.css:38`
- `static/css/style.css:707`

### `h1` — 4 definitions
- `static/css/style.css:60`
- `static/css/style.css:851`
- `static/css/style.css:868`
- `static/css/style.css:894`

### `h2` — 4 definitions
- `static/css/style.css:64`
- `static/css/style.css:855`
- `static/css/style.css:872`
- `static/css/style.css:898`

### `h3` — 4 definitions
- `static/css/style.css:67`
- `static/css/style.css:858`
- `static/css/style.css:875`
- `static/css/style.css:901`

### `*` — 3 definitions
- `static/css/components/utilities.css:108`
- `static/css/style.css:729`
- `static/css/theme.css:592`

### `.about-main` — 3 definitions
- `static/css/about.css:62`
- `static/css/about.css:324`
- `static/css/about.css:360`

### `.affection-bar` — 3 definitions
- `static/css/components/header.css:96`
- `static/css/components/responsive.css:43`
- `static/css/components/responsive.css:67`

### `.btn` — 3 definitions
- `static/css/config.css:504`
- `static/css/style.css:878`
- `static/css/style.css:904`

### `.code-block-header` — 3 definitions
- `static/css/components/code-blocks.css:8`
- `static/css/components/utilities.css:49`
- `static/css/marked.css:338`

### `.content-section` — 3 definitions
- `static/css/about.css:99`
- `static/css/about.css:281`
- `static/css/about.css:336`

### `.footer-link` — 3 definitions
- `static/css/about.css:265`
- `static/css/config.css:596`
- `static/css/home.css:104`

### `.footer-link:hover` — 3 definitions
- `static/css/about.css:275`
- `static/css/config.css:606`
- `static/css/home.css:114`

### `.form-group textarea` — 3 definitions
- `static/css/config.css:123`
- `static/css/config.css:146`
- `static/css/config.css:520`

### `.home-header h1` — 3 definitions
- `static/css/home.css:31`
- `static/css/home.css:127`
- `static/css/home.css:151`

### `.mermaid-header` — 3 definitions
- `static/css/components/utilities.css:49`
- `static/css/marked.css:720`
- `static/css/marked.css:787`

### `.message` — 3 definitions
- `static/css/components/responsive.css:17`
- `static/css/components/utilities.css:31`
- `static/css/components/utilities.css:75`

### `.message-content .callout-important` — 3 definitions
- `static/css/components/messages.css:273`
- `static/css/marked.css:186`
- `static/css/marked.css:207`

### `.message-content .callout-tip` — 3 definitions
- `static/css/components/messages.css:258`
- `static/css/marked.css:171`
- `static/css/marked.css:202`

### `.message-content .callout-warning` — 3 definitions
- `static/css/components/messages.css:263`
- `static/css/marked.css:176`
- `static/css/marked.css:197`

### `.scroll-to-bottom-btn` — 3 definitions
- `static/css/chat.css:51`
- `static/css/components/responsive.css:32`
- `static/css/components/utilities.css:37`

### `.session-action-btn` — 3 definitions
- `static/css/sidebar.css:354`
- `static/css/sidebar.css:512`
- `static/css/sidebar.css:605`

### `.session-action-btn svg` — 3 definitions
- `static/css/sidebar.css:379`
- `static/css/sidebar.css:516`
- `static/css/sidebar.css:609`

### `.sidebar` — 3 definitions
- `static/css/sidebar.css:504`
- `static/css/sidebar.css:593`
- `static/css/sidebar.css:654`

### `.sidebar-content` — 3 definitions
- `static/css/sidebar.css:75`
- `static/css/sidebar.css:559`
- `static/css/sidebar.css:631`

### `.sidebar-section` — 3 definitions
- `static/css/sidebar.css:82`
- `static/css/sidebar.css:563`
- `static/css/sidebar.css:682`

### `.sidebar-section h3` — 3 definitions
- `static/css/sidebar.css:86`
- `static/css/sidebar.css:635`
- `static/css/sidebar.css:686`

### `.sidebar-session-item` — 3 definitions
- `static/css/components/utilities.css:54`
- `static/css/sidebar.css:577`
- `static/css/sidebar.css:597`

### `.tech-grid` — 3 definitions
- `static/css/about.css:145`
- `static/css/about.css:340`
- `static/css/about.css:363`

Notable duplication clusters: `.card`, `.btn`, `.container`, `.hamburger-menu`, `.header-content`, `.header-title`, `.footer-link`, `.loading`, `.config-content`, `.chat-container`, `.input-area`, `.scroll-to-bottom-btn`, `.sidebar`, `.sidebar-header`, `.theme-preview`, and repeated animation keyframes.

## Component inventory and audit targets

- **Button** — `.btn`, `.btn-primary`, `.btn-success`, `.btn-warning`, `.btn-danger`, `.btn-info`, `.sidebar-btn`, `.auth-btn`, `.retry-btn`, `.session-action-btn`
- **Input** — `.form-group input`, `.form-select`, range inputs, BYOK inputs
- **Textarea** — `.form-group textarea`, `.persona-prompt`, knowledge and advanced textareas
- **Message Bubble** — `.message`, `.user-message`, `.ai-message`, `--user-bubble`, `--ai-bubble`, `--message-*`
- **Sidebar** — `.sidebar`, `.sidebar-overlay`, `.sidebar-link`, session items, auth section
- **Header** — `.config-header`, `.home-header`, component header styles, hamburger controls
- **Toolbar / input** — `.input-area`, `.input-container`, toolbar buttons, scroll-to-bottom control
- **Tool Bubble / tool card** — `.tool-card*`, execution, image, weather, generic cards
- **Code Block** — `.code-block*`, `marked.css`, copy controls, syntax highlighting
- **Markdown** — `marked.css`, message markdown selectors, callouts, tables, lists, blockquotes
- **Dialog / overlay** — `.auth-overlay`, secret message dialog generated by `about.js`
- **Dropdown / menu** — `.custom-dropdown`, `.dropdown-selected`, `.dropdown-options`, `.dropdown-option`
- **Toast / notification** — `.session-notification`, `.config-notification` generated by `config.js`

### Component-level findings
- Buttons have several size, radius, shadow, hover, and semantic-color implementations; mobile overrides repeat values.
- Inputs use overlapping focus contracts: `outline`, border color, and shadow rings are defined in more than one stylesheet.
- Sidebar and page headers repeat layout primitives and use different stacking values (`90`, `10000`, `10001`, `10002`).
- Tool cards are comparatively isolated and are the cleanest candidate for a later semantic-token migration.
- Markdown has a large, separate style surface and must be migrated carefully to avoid rendering regressions.
- Toasts and dialogs are partly generated in JavaScript with inline CSS, so CSS-only token migration will not cover them.

## Accessibility observations

- `prefers-reduced-motion` is not present in the current stylesheet set.
- Focus styles exist, but they are distributed and inconsistent; some controls rely on `outline`, others on border/shadow changes.
- Mobile touch targets are not governed by a shared minimum-size token.
- Keyboard behavior exists in page scripts for sidebar/theme shortcuts and accordions, but the component contract is not centralized.
- Theme colors need contrast verification per theme, especially pastel themes, status colors, secondary text, and user bubbles.
- `sidebar.js` injects third-party brand SVG colors directly; these should remain brand exceptions, not become theme tokens.

## Proposed deliverables for approval

1. Design Token Map: Core → Semantic → Theme, with compatibility aliases documented during migration.
2. Component Inventory: the component list above expanded with current values, target tokens, and migration status.
3. Theme Architecture: preserve current theme identities; move only token assignment into theme scopes.
4. CSS Variable Naming Guide: functional names only; no hue-based names for component consumption.
5. Migration Plan: small, reversible component batches, beginning with global primitives and one low-risk component.
6. Accessibility checklist: contrast matrix, focus ring, reduced motion, keyboard, and touch target checks.

## Recommended migration order

1. Freeze current visual behavior with screenshots and a token-usage baseline.
2. Add a documented token contract without deleting legacy aliases.
3. Migrate global primitives: body, typography, focus, motion, spacing helpers, and z-index layers.
4. Migrate one component family at a time: buttons → inputs → sidebar/header → cards/tool cards → messages/markdown → overlays/toasts.
5. Remove duplicate declarations only after all consumers use semantic tokens.
6. Validate each batch with static scans, lint, browser checks, keyboard checks, and reduced-motion checks.

## Guardrails

- No redesign and no new decorative effects.
- Preserve theme names and visual identity.
- Do not change frontend behavior while establishing tokens.
- Do not delete legacy variables until all consumers are migrated and verified.
- Do not collapse Markdown or tool-card styles into generic rules without visual regression checks.

