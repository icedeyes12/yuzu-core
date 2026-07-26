# Phase 4 — Application UX Language

**Status:** Active implementation plan
**Date:** 2026-07-26
**Scope:** Cross-application visual hierarchy and interaction clarity. The chat CX pass in `98d8b28` is the baseline; this plan extends the same language to Home, Configuration, About, Login, and Offline.

## Open questions

None blocking. The implementation will preserve the current dark Yuzu identity, avoid decorative redesign, keep existing routes and runtime behavior, and use Chat as the reference for information hierarchy rather than copying its older container styling.

## Task checklist

### Phase 4.1 — Page layout system

- ☐ Define one shared page frame: header, title/description, content column, footer, and navigation layer.
- ☐ Apply the frame to Home, Configuration, About, Login, and Offline without changing route behavior.
- ☐ Remove duplicated page-header geometry and inconsistent fixed-footer/header spacing.
- ☐ Add automated template/source checks for required landmarks, title hierarchy, and navigation controls.

### Phase 4.2 — Surface and panel language

- ☐ Replace undifferentiated card stacks with explicit section, panel, inset, grouped-list, and status surfaces.
- ☐ Make About read as a document with section rhythm instead of a sequence of floating cards.
- ☐ Make Configuration sections visually subordinate to the page title and reduce nested borders/shadows.
- ☐ Keep provider, knowledge, and runtime controls visually dense only where the task requires density.

### Phase 4.3 — Form and settings experience

- ☐ Establish consistent label, helper text, control, validation, and action-row relationships.
- ☐ Reorganize Configuration by user goal: identity, providers/models, memory/knowledge, generation, and location.
- ☐ Make primary actions unambiguous and keep destructive/secondary actions visually subordinate.
- ☐ Preserve `attachSliderGuard(slider)` and existing config API/state contracts.

### Phase 4.4 — Shared state and mobile behavior

- ☐ Normalize loading, empty, success, warning, and error presentation across pages.
- ☐ Audit mobile spacing, touch target size, sidebar reachability, keyboard-safe composer space, and footer overlap.
- ☐ Consolidate motion timing and add reduced-motion behavior where missing.
- ☐ Keep scroll-to-bottom and sidebar controls secondary to the conversation.

## Implementation phases

### Phase 1 — Shared page frame and layout primitives

**Affected files**

- `file static/css/style.css` — make the shared page frame, typography, focus ring, spacing, surface, and action primitives authoritative.
- `file static/css/components/header.css` — centralize header geometry and title/description alignment used by authenticated pages.
- `file static/css/sidebar.css` — keep navigation layering independent from page content and preserve drawer behavior.
- `file templates/index.html` — align Home with the shared frame while retaining its conversation-first entry point.
- `file templates/config.html` — align Configuration landmarks and page title hierarchy.
- `file templates/about.html` — align About landmarks and document rhythm.
- `file templates/login.html` — map the sign-in surface to the same semantic state and action language without requiring the authenticated sidebar.
- `file templates/offline.html` — remove the isolated inline visual language and use the shared offline state vocabulary.
- `file static/css/home.css`, `file static/css/config.css`, `file static/css/about.css`, `file static/css/login.css` — retain page-specific composition while removing duplicated shell geometry.

**Changes**

1. Introduce shared semantic classes for page frame, page header, title block, content column, section, inset, grouped list, and action row.
2. Use one spacing rhythm and one content-width rule across authenticated pages.
3. Keep headers readable on narrow screens; do not use gradients or animation to create hierarchy.
4. Preserve all existing IDs, links, form names, and JavaScript hooks.

**Automated checks**

- Add a source-level template contract test that renders each page with a minimal context and verifies one `main`, one page title heading, a navigation trigger where applicable, and no page-specific duplicate shell landmarks.
- Add CSS/source checks for required shared class usage and absence of inline `<style>` in `file offline.html`.

### Phase 2 — Surface hierarchy and Configuration form experience

**Affected files**

- `file templates/config.html` — group settings by human goal and distinguish section headings, helper text, controls, provider groups, and status blocks.
- `file static/css/config.css` — reduce card treatment, define form rhythm, control widths, helper/status states, and mobile action behavior.
- `file static/js/config.js` — preserve existing behavior while adding only state classes or semantic hooks required by the new presentation.
- `file templates/about.html` — convert repeated content cards into document sections and grouped lists.
- `file static/css/about.css` — remove hover-lift/card-stack emphasis and establish readable document spacing.
- `file static/css/style.css` — provide shared form, status, and action primitives where page-specific duplication currently exists.

**Changes**

1. Configuration sections become the primary hierarchy; provider cards and knowledge entries become subordinate grouped surfaces.
2. Every control follows `label → control → helper/status → action` where applicable.
3. Primary, secondary, and destructive actions receive distinct visual weight without new decorative styling.
4. About becomes a calm, readable product document rather than six similarly weighted panels.

**Automated checks**

- Add DOM/source assertions for every form control having a label and for helper/status IDs referenced by `aria-describedby` to exist.
- Add tests for configuration slider initialization so every range input remains guarded by `attachSliderGuard`.

### Phase 3 — Shared state language, mobile, and motion

**Affected files**

- `file static/css/components/utilities.css` — normalize loading, empty, success, warning, error, and info state primitives.
- `file static/css/components/skeleton.css` — align skeleton geometry and reduced-motion behavior.
- `file static/css/components/responsive.css` — establish shared narrow-screen spacing and safe-area rules.
- `file static/css/components/header.css`, `file static/css/sidebar.css`, `file static/css/components/input.css`, `file static/css/components/scroll-button.css` — apply shared touch-target, focus, drawer, composer, and secondary-action rules.
- `file static/css/about.css`, `file static/css/config.css`, `file static/css/login.css`, `file static/css/home.css` — remove conflicting mobile and motion overrides.
- `file templates/offline.html` and shared state partials if needed — use the same state vocabulary.

**Changes**

1. Loading, empty, and error states communicate one clear message, status, and next action.
2. Mobile layout accounts for thumb reach, keyboard/composer space, safe areas, sidebar overlay, and footer clearance.
3. Decorative animation is removed or disabled under `prefers-reduced-motion`; state transitions retain consistent timing.
4. Scroll controls remain quiet secondary actions and never compete with the active conversation.

**Automated checks**

- Add source checks for reduced-motion coverage and shared state class usage.
- Add DOM contract checks for interactive controls having accessible names and minimum touch-target classes/attributes.

## 