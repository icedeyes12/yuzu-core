import assert from "node:assert/strict";
import {
	serializeConversationHistory,
	serializeConversationMessage,
	serializeToolCallEvent,
	serializeToolResultEvent,
} from "../static/js/modules/conversation-serializer.js";

const history = serializeConversationHistory([
	{
		id: 1,
		role: "assistant",
		content: null,
		tool_calls: [
			{
				id: "call_1",
				type: "function",
				function: { name: "weather", arguments: "{}" },
			},
		],
		turn_id: "internal-turn",
	},
	{
		id: 2,
		role: "tool",
		tool_call_id: "call_1",
		content: '{"ok":true}',
	},
]);
assert.equal(history[0].id, 1);
assert.equal(history[0].toolCalls[0].name, "weather");
assert.equal(history[0].metadata.turnId, "internal-turn");
assert.equal(history[1].toolResponse.callId, "call_1");
assert.equal(serializeConversationMessage({ role: "provider" }), null);
assert.equal(serializeToolCallEvent({ id: "call_2", name: "x", arguments: {} }).name, "x");
assert.equal(
	serializeToolResultEvent({ call_id: "call_2", name: "x", ok: true }).toolResponse.callId,
	"call_2",
);
