# Yuzu Companion Frontend UX Audit

**Date:** 2026-07-26  
**Scope:** Primary HTML templates, frontend architecture contract, current CSS/JS composition, and recent frontend history.  
**Mode:** Audit and direction only. No application source files were changed.

## Executive judgment

Yuzu's frontend is technically organized around a real conversation runtime, but its product hierarchy still presents the system as an AI application dashboard. The main mismatch is not a missing visual style. It is that the shell, navigation, and home page make modules and configuration visible before the relationship.

The conversation screen is the strongest existing direction: it already gives the chat surface most of the viewport, keeps input fixed, renders messages through `ConversationStore` and `DOMRenderer`, and supports session context in the header. The next work should refine this surface and reduce the prominence of the dashboard shell. It should not begin with a CSS token rewrite, framework migration, or new visual identity system.

## What the current experience communicates

### Opening `/`

The first screen says: “Welcome to a dashboard. Choose Chat or Config.” It shows a greeting, partner name, affection level, and two equal cards. That makes Chat a module beside Config instead of the place where Yuzu exists. The home page also contains animation and ripple behavior that adds presentation but does not clarify the next conversational action.

### Opening `/chat`

The chat screen says: “You are in a focused conversation.” This is much closer to the intended product. The header identifies the partner and current session, the message area is dominant, and the input is persistent. However, the global sidebar still introduces Navigation, Theme, and Sessions as a large operational panel, while the affection progress bar exposes a relationship metric as a persistent UI widget. The message system also has several secondary affordances and tool states that need hierarchy review rather than more decoration.

### Sending a message

The input is easy to find and persistent. The fixed bottom area and send/stop control support the core loop. The main risk is visual weight: the input area, header, sidebar, message bubbles, tool cards, and status treatments all use borders, surfaces, shadows, and accent colors. The conversation can therefore feel like a stack of UI components instead of a calm reading surface.

### Receiving a response

The runtime architecture is appropriate: state belongs to `ConversationStore`, and DOM updates belong to `DOMRenderer`. Typing state and tool results are rendered in the same conversation area. The UX question is not whether to add another renderer. It is whether the rendered states are sufficiently quiet, legible, and ordered so that Yuzu's response remains the main event.

### Switching sessions

Sessions live in the sidebar and can be selected without adding a new navigation system. This is a reasonable continuity mechanism, but it currently competes with theme selection and navigation. Session switching should feel like choosing another thread in the same relationship, not opening an administration drawer.

### Opening `/config`

The configuration page is necessarily dense because it controls identity, provider/model selection, media models, knowledge, generation parameters, feature toggles, and location. The problem is not that this page exists. The problem is that the home surface gives Config equal status with Chat and the shared sidebar presents Config as a primary destination. Configuration should remain a deliberate maintenance surface, not part of the first-run product story.

## Five largest mismatches against the digital-entity vision

### 1. Home is a module chooser instead of a conversational entry point

`templates/index.html` offers two equal cards: Chat and Config. This encodes “application dashboard” as the primary mental model.

**Priority:** P0 — fix the product hierarchy before styling details.

### 2. The shared sidebar is an operations console

`templates/sidebar.html` combines four navigation links, a theme selector, and session management. `static/css/sidebar.css` gives that panel substantial visual and interaction weight. These are useful controls, but they should be secondary to the current conversation.

**Priority:** P0 — simplify what the sidebar asks the user to manage.

### 3. Persistent relationship metrics compete with presence

The affection display in `templates/chat.html` is a progress bar with a numerical implication. It may be meaningful as a product concept, but its current persistent placement risks making the relationship feel like a gamified status system. It should not be removed blindly; it should be tested as a quieter identity/state cue.

**Priority:** P1 — reduce prominence, preserve runtime behavior.

### 4. Visual language has accumulated too many competing signals

The design-system audit found 21 CSS files, 7,069 CSS lines, 73 unique variable names, 10 used-but-undefined variables, 738 hardcoded color references, and 135 selectors with repeated definitions. This is evidence of accumulated visual decisions, not a reason to rewrite everything. The practical effect is inconsistent emphasis: gradients, shadows, borders, cards, status colors, and motion all compete for attention.

**Priority:** P1 — consolidate only the chat shell and visible states first.

### 5. The frontend exposes implementation concepts too easily

Provider, model, memory, advanced generation parameters, theme, and location are all accessible through the main application shell. They are legitimate capabilities, but they are not the relationship. The UI should preserve access while making those concepts deliberately secondary.

**Priority:** P1 — separate “talking to Yuzu” from “maintaining Yuzu.”

## Problems of hierarchy versus styling

### Hierarchy/composition problems

- `/` assigns Chat and Config equal status.
- The shared sidebar assigns Navigation, Theme, and Sessions similar status.
- The chat header spends persistent space on affection progress.
- The shell does not clearly distinguish primary conversation from maintenance surfaces.
- Tool output, session controls, and system status need a clearer reading order.
- The default route does not immediately place the user in the relationship.

### Styling problems

- Too many surfaces, borders, shadows, and accent treatments are visible at once.
- Several pages use gradients or decorative effects where a plain state would be clearer.
- CSS contains legacy aliases and duplicated selectors, making visual changes unpredictable.
- Motion appears in home cards, ripples, loading/typing states, and controls; not all motion communicates useful state.
- Typography and spacing are serviceable but do not yet establish a distinct reading rhythm for a private conversation.

**Important:** Styling changes cannot solve the first group. Reworking colors or adding a more fashionable visual language while keeping the same hierarchy would produce a more polished dashboard, not a more coherent Yuzu.

## Protected behavior to preserve

- Native function-calling and structured tool events.
- `ConversationStore` as conversation state owner.
- `DOMRenderer` as DOM owner.
- Existing SSE and history contracts.
- Session URLs and session switching behavior.
- Multimodal attachments and tool cards.
- BYOK behavior and browser-only key storage.
- Accessibility labels, focus behavior, and reduced-motion support.
- The existing per-page stylesheet layout unless a narrowly scoped change proves necessary.

## Recommended information architecture

```text
Yuzu
└── Conversation (default and primary)
    ├── Current session
    ├── Messages and contextual tool activity
    ├── Composer
    └── Secondary drawer
        ├── New conversation
        ├── Other conversations
        ├── Appearance
        ├── Configuration
        └── About
```

The current sidebar can evolve into this secondary drawer without changing backend routes or conversation state. The first implementation should not introduce a new navigation framework.

## Chat-screen composition specification

### Primary zone

- A calm, full-height reading surface.
- Messages centered in a readable column with generous horizontal breathing room.
- Assistant content should not look like a raised card by default.
- User content should be distinct through alignment and a restrained surface, not heavy ornament.
- Tool activity should occupy the conversation flow and remain compact when complete.

### Header

- Left: menu control and Yuzu identity.
- Center or adjacent: current session name, only when useful.
- Right: one quiet status/relationship cue; do not make a metric the dominant header element.
- Keep the header stable while the conversation scrolls.

### Composer

- The most obvious action after the message stream.
- Large enough for natural writing, visually quieter than a primary button panel.
- Send/stop state must be immediately understandable.
- Avoid additional controls in the composer until a real workflow requires them.

### Secondary drawer

- Open only on demand.
- First section: current/other conversations and New Chat.
- Second section: appearance.
- Last sections: Configuration and About.
- Avoid making the user scan system terms before reaching sessions.

### Empty state

- Should address the person and invite a conversation, not advertise capabilities.
- It may mention one or two natural examples, but should not become a feature catalog.
- The first actionable target should be the composer.

### Runtime states

- Waiting: quiet, no unnecessary status chrome.
- Generating: one clear typing/working state near Yuzu's response.
- Using a tool: compact contextual event; expand details only when needed.
- Finished: return attention to the response, not the tool machinery.
- Error: explain what failed and what the user can do, in the conversation area.

## Prioritized work sequence

### P0 — Establish the product hierarchy

1. Keep `/chat/{session_id}` as the real primary destination.
2. Decide whether `/` should redirect to the active chat or become a quiet conversation-oriented landing state. The preferred direction is active chat, but this is a product-level route decision.
3. Reframe the shared sidebar as a secondary drawer and put sessions before maintenance controls.
4. Do not change API, SSE, store, or renderer contracts.

### P1 — Refine the chat surface

1. Simplify header emphasis and make Yuzu/session identity clearer.
2. Reduce visual weight of the affection display without deleting its data.
3. Tune message rhythm, assistant/user distinction, and tool-card density.
4. Make empty, generating, completed-tool, and error states read as one coherent conversation.
5. Add or verify reduced-motion behavior for decorative home and chat motion.

### P2 — Demote maintenance surfaces

1. Keep Config functional, but make its purpose explicit as maintenance/customization.
2. Group configuration by human goal rather than provider implementation where possible; do not rewrite the form in the first pass.
3. Move appearance selection out of the session/navigation flow if the drawer becomes crowded.

### P3 — Cleanup after the experience is right

1. Remove dead home-page behavior such as session fetches targeting absent markup, if confirmed unused.
2. Consolidate CSS aliases and duplicate selectors incrementally.
3. Remove obsolete visual helpers only after browser behavior is verified.

## What not to do next

- Do not start by replacing all CSS variables.
- Do not introduce glassmorphism, gradient meshes, animated backgrounds, or an orb/avatar as a substitute for hierarchy.
- Do not rewrite the frontend into React/Vite.
- Do not create another state or renderer abstraction.
- Do not delete files merely to reduce the file count.
- Do not change backend behavior as part of a visual pass.

## Definition of done for the first UI pass

A first pass is successful when a person can open Yuzu and immediately understand that the conversation is the product; can read and write without visual competition; can see when Yuzu is responding or using a tool; and can reach sessions/configuration through secondary controls without losing the sense of continuity.
