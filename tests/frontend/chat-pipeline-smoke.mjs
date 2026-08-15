// Chat pipeline smoke test: drives the ported ConversationStore + EventRouter
// with the exact SSE wire contract emitted by /api/v1/send_message_stream and
// verifies the store reaches the expected terminal state. Runs without a
// browser: store/event-router/renderer modules are exercised with minimal DOM
// stubs via Node's module loader.
import assert from "node:assert/strict";

// ── Minimal DOM stubs (module-level side effects need these globals) ──
class FakeElement {
	constructor(tag = "div") {
		this.tagName = tag.toUpperCase();
		this.children = [];
		this.classList = { add() {}, remove() {}, contains: () => false };
		this.dataset = {};
		this.style = {};
		this.attributes = {};
	}
	appendChild(child) {
		this.children.push(child);
		return child;
	}
	scrollTo() {}
	remove() {}
	querySelector() {
		return null;
	}
	querySelectorAll() {
		return [];
	}
	insertAdjacentHTML() {}
	setAttribute(k, v) {
		this.attributes[k] = String(v);
	}
	getAttribute(k) {
		return this.attributes[k];
	}
	closest() {
		return null;
	}
	set innerHTML(v) {
		this._html = v;
	}
	get innerHTML() {
		return this._html || "";
	}
	set textContent(v) {
		this._text = v;
	}
	get textContent() {
		return this._text || "";
	}
}

globalThis.window = {
	requestAnimationFrame: (cb) => setTimeout(cb, 0),
	cancelAnimationFrame: (id) => clearTimeout(id),
	location: { pathname: "/chat/abc", search: "" },
	hljs: { highlightElement() {} },
	renderMathInElement: undefined,
	addEventListener() {},
	removeEventListener() {},
	setTimeout,
	clearTimeout,
};

globalThis.document = {
	getElementById: () => new FakeElement(),
	querySelector: () => null,
	querySelectorAll: () => [],
	createElement: (tag) => new FakeElement(tag),
	addEventListener() {},
	removeEventListener() {},
	body: new FakeElement("body"),
};

globalThis.requestAnimationFrame = globalThis.window.requestAnimationFrame;
globalThis.addEventListener = () => {};
globalThis.setTimeout = setTimeout;
globalThis.clearTimeout = clearTimeout;

// The modules under test are byte-identical ports of static/js/modules/*, so
// the frontend copy is what ships. Load it with Node's ESM loader.
const { chatStore } = await import(
	"../../web/src/modules/store.js"
);
const { eventRouter } = await import(
	"../../web/src/modules/event-router.js"
);

const SESSION = "smoke-session";
eventRouter.setActiveView(SESSION);

// ── Mirror multimodal.js's send flow: open an assistant bubble, then stream ──
chatStore.beginAssistantMessage();
eventRouter.registerStream(SESSION, new AbortController());

// ── Simulate the exact event sequence the backend stream emits ──
const streamEvents = [
	{ type: "token", content: "Hello" },
	{ type: "token", content: ", world!" },
	{ type: "tool_call", data: { id: "call_1", name: "bash", arguments: "{}" } },
	{ type: "tool_result", data: { tool_call_id: "call_1", status: "completed", content: "ok" } },
	{ type: "token", content: "Result above." },
	{ type: "done", turn_id: "turn-1" },
];

for (const raw of streamEvents) {
	eventRouter.handleEvent(SESSION, JSON.stringify(raw));
}
eventRouter.finishStream(SESSION);

// ── Assertions on the terminal store state ──
const assistantMessages = chatStore.messages.filter(
	(m) => m.role === "assistant",
);
assert.ok(assistantMessages.length >= 1, "expected at least one assistant message");

const first = assistantMessages[0];
assert.equal(first.content, "Hello, world!", "tokens should be concatenated");
assert.equal(first.metadata.isFrozen, true, "assistant message should freeze after done");
assert.equal(
	first.toolCalls?.[0]?.name,
	"bash",
	"tool call should be recorded on the assistant message",
);

assert.equal(chatStore.isGenerating, false, "generation should finish after done");
assert.equal(chatStore.error, null, "no error expected on a clean stream");

// The post-tool token pass starts a fresh bubble, so the second assistant
// message carries the final response text.
const last = assistantMessages[assistantMessages.length - 1];
assert.equal(last.content, "Result above.", "post-tool tokens land in a new bubble");

// ── Mid-stream session switch (sidebar switchSession path) ────────────────
// A second session starts generating; while its stream is live, the user
// switches away. The sidebar calls eventRouter.cancelStream(oldSession), then
// handleSessionSwitch(newSession) loads fresh history. Verify the old
// stream is torn down (isGenerating clears) and the store no longer accepts
// stray tokens for the abandoned session.
const OLD = "old-session";
const NEW = "new-session";
eventRouter.setActiveView(OLD);
chatStore.beginAssistantMessage();
eventRouter.registerStream(OLD, new AbortController());
eventRouter.handleEvent(OLD, JSON.stringify({ type: "token", content: "partial" }));
assert.equal(
	chatStore.isGenerating,
	true,
	"generation active while the stream is in flight",
);

// User clicks another session in the sidebar -> cancelStream aborts the
// in-flight stream and finishes the abandoned generation.
eventRouter.cancelStream(OLD);
assert.equal(chatStore.isGenerating, false, "abandoned stream is cancelled");

// The cancelled bubble freezes so late chunks cannot mutate it.
const cancelled = chatStore.messages.at(-1);
assert.equal(cancelled.role, "assistant");
assert.equal(cancelled.metadata.isFrozen, true, "cancelled message freezes");

// handleSessionSwitch(NEW) -> setActiveView + loadChatHistory reset state.
eventRouter.setActiveView(NEW);
chatStore.loadHistory(NEW, [], false);
assert.equal(chatStore.sessionId, NEW, "store switches to the new session");
assert.equal(chatStore.messages.length, 0, "new session starts empty");
assert.equal(chatStore.isGenerating, false);

// Stray events for the abandoned session are ignored by the router.
eventRouter.setActiveView(OLD);
eventRouter.handleEvent(OLD, JSON.stringify({ type: "token", content: "late" }));
assert.equal(
	chatStore.messages.find((m) => m.content === "late"),
	undefined,
	"stray tokens for the abandoned session are dropped",
);

eventRouter.setActiveView(NEW);

console.log(
	`chat pipeline smoke passed: ${chatStore.messages.length} store messages, ${assistantMessages.length} assistant bubbles, mid-stream switch verified`,
);
