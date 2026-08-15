const VALID_ROLES = new Set(["user", "assistant", "tool", "system"]);

function createLocalId(prefix = "message") {
	const random = Math.random().toString(36).slice(2, 10);
	return `${prefix}_${Date.now()}_${random}`;
}

function stringifyArguments(value) {
	if (typeof value === "string") return value;
	if (value === undefined || value === null) return "";
	try {
		return JSON.stringify(value);
	} catch (_error) {
		return String(value);
	}
}

function parseObjectContent(content) {
	if (typeof content !== "string" || !content.trim()) return {};
	try {
		const parsed = JSON.parse(content);
		return parsed && typeof parsed === "object" && !Array.isArray(parsed)
			? parsed
			: {};
	} catch (_error) {
		return {};
	}
}

function normalizeToolCall(raw, defaultStatus = "completed") {
	if (!raw || typeof raw !== "object") return null;
	const fn =
		raw.function && typeof raw.function === "object" ? raw.function : {};
	const id = typeof raw.id === "string" && raw.id.trim() ? raw.id : null;
	const name = raw.name || fn.name;
	if (!id || typeof name !== "string" || !name.trim()) return null;
	return {
		id,
		name: name.trim(),
		arguments: stringifyArguments(raw.arguments ?? fn.arguments),
		status: raw.status || defaultStatus,
	};
}

function normalizeToolCalls(rawCalls, defaultStatus = "completed") {
	if (!Array.isArray(rawCalls)) return [];
	return rawCalls
		.map((raw) => normalizeToolCall(raw, defaultStatus))
		.filter(Boolean);
}

function normalizeAttachments(rawAttachments) {
	return Array.isArray(rawAttachments) ? rawAttachments : [];
}

function normalizeMetadata(raw, options = {}) {
	const source =
		raw.metadata && typeof raw.metadata === "object" ? raw.metadata : {};
	return {
		isFrozen: Boolean(options.isFrozen ?? raw.isFrozen ?? source.isFrozen),
		turnId: raw.turnId || raw.turn_id || source.turnId || null,
	};
}

export function serializeConversationMessage(raw = {}, options = {}) {
	const input = raw && typeof raw === "object" ? raw : {};
	if (!VALID_ROLES.has(input.role)) return null;

	const role = input.role;
	const toolCalls = normalizeToolCalls(input.toolCalls ?? input.tool_calls);
	const parsedContent = parseObjectContent(input.content);
	const callId =
		input.toolResponse?.callId ||
		input.tool_call_id ||
		parsedContent.call_id ||
		parsedContent.tool_call_id ||
		null;
	const rawToolResponse =
		input.toolResponse && typeof input.toolResponse === "object"
			? input.toolResponse
			: role === "tool"
				? { ...parsedContent, ...input }
				: null;
	const toolResponse =
		rawToolResponse && callId
			? {
					callId,
					name: rawToolResponse.name || input.name || "unknown",
					ok: rawToolResponse.ok !== false,
					data:
						rawToolResponse.data && typeof rawToolResponse.data === "object"
							? rawToolResponse.data
							: {},
					error: rawToolResponse.error || "",
					status:
						rawToolResponse.status ||
						(rawToolResponse.ok === false ? "error" : "completed"),
				}
			: null;
	const content =
		input.content === null || input.content === undefined
			? role === "tool" && toolResponse
				? JSON.stringify({
						call_id: toolResponse.callId,
						name: toolResponse.name,
						ok: toolResponse.ok,
						data: toolResponse.data,
						error: toolResponse.error,
					})
				: ""
			: String(input.content);

	return {
		id: input.id || input.message_id || createLocalId("message"),
		role,
		content,
		attachments: normalizeAttachments(input.attachments),
		toolCalls,
		toolResponse,
		timestamp: input.timestamp || new Date().toISOString(),
		metadata: normalizeMetadata(input, options),
	};
}

export function serializeConversationHistory(history, options = {}) {
	if (!Array.isArray(history)) return [];
	return history
		.map((message) => serializeConversationMessage(message, options))
		.filter(Boolean);
}

export function serializeToolCallEvent(raw) {
	const message = serializeConversationMessage(
		{
			role: "assistant",
			toolCalls: [raw],
		},
		{ isFrozen: false },
	);
	if (!message?.toolCalls.length) return null;
	return {
		...message.toolCalls[0],
		status: raw?.status || "started",
	};
}

export function serializeToolResultEvent(raw) {
	if (!raw || typeof raw !== "object") return null;
	const callId = raw.call_id || raw.callId || raw.tool_call_id;
	if (typeof callId !== "string" || !callId.trim()) return null;
	return serializeConversationMessage({
		id: `tool_${callId}`,
		role: "tool",
		content: JSON.stringify(raw),
		toolResponse: {
			callId,
			name: raw.name || "unknown",
			ok: raw.ok !== false,
			data: raw.data && typeof raw.data === "object" ? raw.data : {},
			error: raw.error || "",
			status: raw.ok === false ? "error" : "completed",
		},
		timestamp: raw.timestamp,
	});
}

export function serializeToolResponse(raw) {
	return serializeToolResultEvent(raw);
}

export function serializeToolCallMessage(raw) {
	const toolCall = serializeToolCallEvent(raw);
	if (!toolCall) return null;
	return serializeConversationMessage({
		role: "assistant",
		content: "",
		toolCalls: [toolCall],
	});
}
