# Architectural Master Roadmap

**Goal:** Transform the Yuzu backend and frontend into a deterministic, simple-to-explain structure governed strictly by the flow:
`Request → Transport → Application → Canonical Orchestration → Persistence → Event → Transport → Presentation`.

The orchestrator has now been stripped of arbitrary modes (e.g. Synthesis, Ephemeral loops). Future work focuses heavily on enforcing separation of concerns between Database models, Application layers, and Transports (HTTP/SSE) before moving toward any visual interface redesigns.

---

## The Master Refactor Strategy

### Phase 2: Canonical Message Model (Architecture First)
- **Do not jump to implementation.** Design the Canonical Message Model first.
- **Identify current state:** Audit all message representations (DB rows, provider payloads, tool payloads, streaming, SSE, REST, frontend).
- **Design:** Create a single, provider-agnostic, transport-agnostic, frontend-agnostic canonical model (`ConversationEvent`).
- **Ownership:** Clearly define ownership for every property. No ambiguous "misc" or "metadata" accumulators.
- **Attachments:** Define strict attachment ownership (e.g., generated images belong to `ToolEvent`, not `AssistantEvent`).
- **Constraints:** Favor extensibility through composition over optional field accumulation. Keep the model minimal and strict.
- **Deliverable:** Produce a design document with the proposed model, ownership matrix, and database compatibility assessment before writing code.

### Phase 3: Database Schema Audit
- Assess `profiles`, `chat_sessions`, `messages`, and `memory` structures.
- Does the current schema map cleanly to the new `ConversationEvent` model?
- Are we storing provider schemas correctly?
- Cleanse schema drift, foreign keys, and Normalization checks to support the new event-driven architecture.

### Phase 4: Application Layer (The Orchestration Boundary)
- Create a clear `ConversationService`.
- Extract endpoints that talk directly to `db.add_message()` or orchestrator components behind this abstraction.
- Enforce that the Application Layer owns the business logic (orchestrator execution), but knows nothing about how it was triggered (REST, CLI, SSE).

### Phase 5: Transport Layer (REST/SSE/API)
- Refactor FastAPI routers to exclusively call `ConversationService`.
- Standardize REST serializers mapping `ConversationEvent` directly into JSON.
- Standardize SSE payload generation mapping `ConversationEvent` into `StreamToolEvent`/delta packets.
- Ensure API controllers do not contain orchestration or logic steps.

### Phase 6: Provider Layer (Serialization Boundary)
- Abstract AI provider APIs away completely.
- They must only receive the Canonical `Conversation` and output `ConversationEvent`. 
- No provider API shapes or raw dictionary manipulation should leak into `orchestrator.py` or the `Application Layer`.

### Phase 7: Frontend Runtime Audit
- Discover how the frontend parses SSE streams and history JSON.
- Document the renderer hierarchy (`history.js`, `renderer.js`, `validator.js`).
- Profile who owns state: The DOM? The Validator? Redux/Context (if any)?
- Expose the patching, slicing, and dice-based updating of the UI.

### Phase 8: Frontend Runtime Architecture
- Audit frontend state ownership (Conversation, Stream, Message, Tool, Abort, Rerender).
- Design `ConversationStore` (single source of truth, simple object, no Redux).
- Implement event-driven streams (`AssistantStarted`, `ToolProgress`, etc.) replacing string concatenation.
- Enforce message immutability (freeze after completion, no retroactive `innerHTML` patching).

### Phase 9: UX/UI Redesign
- With the frontend engine sanitized, redesign the interface visuals.
- Build clean visual representations of Tool Execution vs Standard Response streams.

### Phase 10: Memory Architecture
- Re-map vector memories, search structures, and semantic facts onto the new canonical message flows natively.

### Phase 11: Runtime Validator
- Prove the architecture architecture correctly handles execution limits under stress, without relying on features/optimizations.
- Certify the architecture across the following boundaries:
    - **Conversation Invariants:** One state owner, no DOM-derived logic.
    - **Runtime Rules:** Transport interpreted exactly once, zero legacy paths.
    - **Tool Sandbox:** Visual isolation from presentation, immutable output execution.
    - **Memory Purity:** No bypass fetching, no cross-tenant leakage.
    - **Navigation Binding:** Single-owner paths.
    - **Streaming Matrix:** Clean transitions across wait/think/tool/pause/complete.
- Provide a **Final Certification Report** and document remaining debt.

### Complete History & Details
Full audit histories for completed phases are available in `docs/roadmap-history/`:
- [Phase 1: DB Schema Migration](docs/roadmap-history/PHASE1_DB_SCHEMA.md)
- [Phase 2: DB Connection Migration](docs/roadmap-history/PHASE2_DB_CONNECTION.md)
- [Phase 3: DB API Security](docs/roadmap-history/PHASE3_DB_API_SECURITY.md)
- [Phase 4: Application Layer](docs/roadmap-history/PHASE4_APP_LAYER.md)
- [Phase 5: Transport Layer](docs/roadmap-history/PHASE5_TRANSPORT_LAYER.md)
- [Phase 6: Provider Layer](docs/roadmap-history/PHASE6_PROVIDER_LAYER.md)
- [Phase 8: Frontend Runtime](docs/roadmap-history/PHASE8_FRONTEND_OWNERSHIP.md)
- [Phase 10: Memory Architecture](docs/roadmap-history/PHASE10_MEMORY_ARCHITECTURE.md)
