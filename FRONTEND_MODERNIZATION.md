# Frontend Modernization Implementation Summary

## Overview

This document summarizes the frontend modernization changes made to yuzu-companion, covering CSS architecture, rendering engine upgrades, and SSE streaming implementation.

---

## Phase 1: CSS Architecture & Theme Refactoring

### 1.1 New File: `file static/css/marked.css`

- **Created** new dedicated stylesheet for markdown rendering
- Extracted \~350 lines of markdown styling from `file chat.css`
- Provides consistent styling for:
  - Typography (h1-h6, paragraphs, lists)
  - Links, blockquotes, callouts
  - Tables, code blocks, inline code
  - Mermaid diagrams (new)
  - Images, details/summary
  - Streaming cursor animation (new)

### 1.2 Updated: `file static/css/theme.css`

- **Refactored** variable names from color-specific to semantic:
  - `--accent-pink` → `--accent-primary`
  - `--accent-lavender` → `--accent-secondary`
  - `--accent-mint` → `--accent-tertiary`
  - Added `--accent-muted`
- **Added legacy aliases** for backward compatibility
- **Implemented 2 new themes**:
  - **suisei** (Stellar Night): Deep midnight blue with cyan accents
  - **tokyonight** (Tokyo Night): Classic Tokyo Night color palette

### 1.3 Theme Preview Colors

- Added CSS classes for theme dropdown previews:
  - `.suisei-preview`
  - `.tokyonight-preview`

---

## Phase 2: Rendering Engine Upgrades

### 2.1 Updated: `file templates/chat.html`

**Library Version Upgrades:**

| Library | Old Version | New Version |
| --- | --- | --- |
| marked.js | v11.1.1 | v18.0.2 |
| mermaid.js | Not installed | v11.4.0 |
| highlight.js theme | github-dark | tomorrow-night-blue |

**New CSS Import:**

```html
<link rel="stylesheet" href="{{ url_for('static', path='css/marked.css') }}">
```

**New Theme Options:**

- Added "Stellar Night" (suisei)
- Added "Tokyo Night" (tokyonight)

### 2.2 Updated: `file static/js/renderer.js`

**Mermaid.js Integration:**

- Added `isMermaidReady` flag
- Initialize mermaid with dark theme in `initializeLibraries()`
- Detect `mermaid` language in custom code renderer
- Return `<div class="mermaid-container">` for mermaid blocks
- Added `initializeMermaidDiagrams(container)` async method

**Code Block Rendering:**

```javascript
if (normalizedLang === 'mermaid' && this.isMermaidReady) {
    const id = `mermaid-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
    return `<div class="mermaid-container" data-mermaid-id="${id}">
        <div class="code-block-header">
            <span class="code-language">mermaid</span>
        </div>
        <pre class="mermaid" id="${id}">${this.escapeHtml(code)}</pre>
    </div>`;
}
```

---

## Phase 3: SSE Streaming Implementation

### 3.1 Updated: `file static/js/chat.js`

**New Global State:**

```javascript
let currentStreamMessage = null;
let streamBuffer = '';
let streamRenderTimeout = null;
const STREAM_RENDER_DEBOUNCE_MS = 50;
```

**New Methods in MultimodalManager:**

1. `sendMessageStreaming(message)`

   - Uses `/api/send_message_stream` endpoint
   - Creates message element immediately (empty)
   - Reads SSE stream via `ReadableStream`
   - Accumulates chunks and schedules incremental renders

2. `createStreamingMessageElement(role)`

   - Creates message DOM element with streaming cursor
   - Includes timestamp and copy button

3. `scheduleStreamRender(contentDiv)`

   - Debounces render updates (50ms)
   - Prevents excessive DOM updates

4. `renderStreamContent(contentDiv)`

   - Reuses existing `renderer.render()` for markdown
   - Applies hljs highlighting to new code blocks
   - Initializes mermaid diagrams
   - Shows blinking cursor for visual feedback

5. `finalizeStreamMessage(contentDiv, finalContent)`

   - Final render without cursor
   - Final highlight/mermaid pass
   - Updates copy button handler

6. `cleanupStreamState()`

   - Resets streaming state variables

### 3.2 CSS: Streaming Cursor Animation

**Added to `file static/css/marked.css`:**

```css
.streaming-cursor {
    display: inline-block;
    color: var(--accent-primary);
    animation: cursorBlink 0.8s infinite;
    margin-left: 2px;
    font-weight: bold;
}

@keyframes cursorBlink {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
}

.message[data-streaming="true"] {
    animation: pulse 1.5s ease-in-out infinite;
}
```

---

## Phase 4: Typing Indicator System

### 4.1 Architecture Overview

The typing indicator is implemented as a **dynamic in-flow message element**, not a static overlay.

```markdown
┌─────────────────────────────────────────────┐
│  .chat-container (flex-column, gap: 0.8rem) │
│  ┌─────────────────────────────────────┐   │
│  │ .message.user                       │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │ .message.ai                         │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │ .typing-indicator-message ← DYNAMIC │   │
│  │   (appended via JS, in-flow)        │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ↓ padding-bottom (dynamic via JS)          │
├─────────────────────────────────────────────┤
│  .input-area (position: fixed, bottom: 0)   │
└─────────────────────────────────────────────┘
```

### 4.2 Implementation Details

**File: `file static/js/chat.js`**

```javascript
// Global state
let _typingIndicatorElement = null;
let _typingIndicatorShownAt = 0;
const TYPING_INDICATOR_MIN_DURATION_MS = 300;

function showTypingIndicator() {
    // Remove any existing indicator first
    hideTypingIndicator(true);

    // Ensure layout is up-to-date before appending
    if (typeof window.updateDynamicLayout === "function") {
        window.updateDynamicLayout();
    }

    const chatContainer = document.getElementById("chatContainer");
    const msg = document.createElement("div");
    msg.className = "message ai typing-indicator-message";
    msg.id = "typingIndicatorMessage";

    const dots = document.createElement("div");
    dots.className = "typing-dots";
    dots.innerHTML = "<span></span><span></span><span></span>";
    msg.appendChild(dots);

    chatContainer.appendChild(msg);
    _typingIndicatorElement = msg;
    _typingIndicatorShownAt = Date.now();

    scrollToBottom();
}

function hideTypingIndicator(force = false) {
    if (!_typingIndicatorElement) return;

    const elapsed = Date.now() - _typingIndicatorShownAt;
    const remaining = TYPING_INDICATOR_MIN_DURATION_MS - elapsed;

    if (force || remaining <= 0) {
        _typingIndicatorElement.remove();
        _typingIndicatorElement = null;
    } else {
        setTimeout(() => {
            if (_typingIndicatorElement) {
                _typingIndicatorElement.remove();
                _typingIndicatorElement = null;
            }
        }, remaining);
    }
}
```

### 4.3 CSS Styling

**File: `file static/css/chat.css`**

```css
/* ==================== TYPING INDICATOR MESSAGE (in-flow) ==================== */
.typing-indicator-message {
    align-self: flex-start;
    margin-bottom: 0.5rem;
    background: var(--message-ai-bg);
    border: 1px solid var(--border-ai);
    padding: 0.8rem 1rem;
    border-radius: 12px;
    max-width: 60px;
    animation: fadeIn 0.3s ease;
}

.typing-indicator-message .typing-dots {
    display: flex;
    gap: 0.4rem;
    justify-content: center;
    align-items: center;
}

.typing-indicator-message .typing-dots span {
    width: 8px;
    height: 8px;
    background: var(--accent-primary, var(--accent-color));
    border-radius: 50%;
    animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator-message .typing-dots span:nth-child(1) { animation-delay: 0s; }
.typing-indicator-message .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator-message .typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.7; }
    30% { transform: translateY(-10px); opacity: 1; }
}
```

### 4.4 Dynamic Layout System

**Why dynamic?** The input area height changes based on:

- Textarea content (auto-resize)
- Multimodal toggle button presence
- Mobile vs desktop viewport

**File: `file static/js/chat.js`**

```javascript
function initializeInputBehavior() {
    const input = document.getElementById("messageInput");
    const chatContainer = document.getElementById("chatContainer");

    function updateDynamicLayout() {
        const inputArea = input.closest(".input-area");
        const inputAreaHeight = inputArea.offsetHeight;

        if (chatContainer) {
            const headerHeight = 48;
            const bottomMargin = 60; // Extra margin for visibility
            chatContainer.style.paddingTop = `${headerHeight + 8}px`;
            chatContainer.style.paddingBottom = `${inputAreaHeight + bottomMargin}px`;
        }
    }

    // Initial call
    updateDynamicLayout();

    // Triggers
    input.oninput = () => { updateDynamicLayout(); };
    window.addEventListener("resize", updateDynamicLayout);

    const inputArea = input.closest(".input-area");
    new ResizeObserver(() => updateDynamicLayout()).observe(inputArea);

    window.updateDynamicLayout = updateDynamicLayout;
}
```

### 4.5 Lifecycle Integration

| Event | Action |
| --- | --- |
| User sends message | `showTypingIndicator()` called immediately |
| First SSE chunk received | `hideTypingIndicator()` called, streaming message displayed |
| Stream error | `hideTypingIndicator()` in `finally` block |
| `/imagine` command | `showTypingIndicator()` → fetch → `hideTypingIndicator()` |

### 4.6 Common Pitfalls (Historical)

1. **Two competing systems**: Legacy static `#typingIndicator` HTML + dynamic JS. Fixed by removing legacy.
2. **Hardcoded padding**: CSS media query `@media (max-width: 768px)` overrode dynamic JS padding. Fixed by removing hardcoded padding from media query.
3. `margin-top: auto`: Pushed element to bottom edge behind input area. Fixed by removing.
4. **Hardcoded** `min-height`: Legacy `calc(100vh - 48px - 192px)` conflicted with dynamic padding. Fixed by removing.
5. **Browser quirks**: Some mobile browsers (Queta) require fullscreen for correct viewport calculation. Kiwi Browser works correctly.

### 4.7 Files Summary

| File | Role |
| --- | --- |
|  | No static typing indicator element (removed) |
|  | `showTypingIndicator()`, `hideTypingIndicator()`, `updateDynamicLayout()` |
|  | `.typing-indicator-message` styling, `@keyframes typing` |

---

## File Changes Summary

| File | Action | Lines Changed |
| --- | --- | --- |
|  | Created | \~450 lines |
|  | Rewritten | \~350 lines |
|  | Updated | \~50 lines added |
|  | Updated | \~100 lines added |
|  | Updated | \~20 lines changed |

---

## Testing Checklist

- [ ]  Theme switching works for all 9 themes

- [ ]  Mermaid diagrams render correctly

- [ ]  Code blocks have Tomorrow Night Blue theme

- [ ]  SSE streaming shows incremental text

- [ ]  Streaming cursor blinks during response

- [ ]  Code highlighting works during and after streaming

- [ ]  Copy buttons work on finalized messages

- [ ]  Mobile responsive design intact

---

## Browser Compatibility

| Feature | Chrome | Firefox | Safari | Edge |
| --- | --- | --- | --- | --- |
| SSE Streaming | ✅ | ✅ | ✅ | ✅ |
| ReadableStream | ✅ | ✅ | ✅ | ✅ |
| Mermaid.js | ✅ | ✅ | ✅ | ✅ |
| CSS Variables | ✅ | ✅ | ✅ | ✅ |
| CSS Animations | ✅ | ✅ | ✅ | ✅ |

---

## Next Steps (Optional)

1. **Performance Optimization**: Consider virtual scrolling for long chat histories
2. **Accessibility**: Add ARIA labels for streaming messages
3. **Error Recovery**: Implement retry logic for dropped SSE connections
4. **Offline Support**: Cache mermaid.js and marked.js locally