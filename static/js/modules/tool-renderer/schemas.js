// FILE: static/js/modules/tool-renderer/schemas.js
// DESCRIPTION: Frontend TypeScript-style interfaces as runtime validators.
//             The backend is the canonical schema source (Pydantic); these
//             validators catch drift early at the wire boundary and
//             guarantee downstream renderers can rely on field shapes.

/**
 * @typedef {Object} BaseToolResultData
 * @property {string} schema_kind       - canonical dispatch key
 * @property {number} [schema_version]  - wire schema version
 * @property {string} [rendering]       - optional specialised card hint
 * @property {boolean} [ok]             - success flag
 * @property {string} [error_message]   - error text when ok=false
 */

const ToolPayloadValidationError = class ToolPayloadValidationError extends Error {
	constructor(message, payload) {
		super(message);
		this.name = "ToolPayloadValidationError";
		this.payload = payload;
	}
};

function expectObject(payload, schemaKind) {
	if (
		payload === null ||
		typeof payload !== "object" ||
		Array.isArray(payload)
	) {
		throw new ToolPayloadValidationError(
			`Expected object for ${schemaKind}, got ${typeof payload}`,
			payload,
		);
	}
}

function requireField(payload, field, schemaKind) {
	expectObject(payload, schemaKind);
	if (
		!(field in payload) ||
		payload[field] === undefined ||
		payload[field] === null
	) {
		throw new ToolPayloadValidationError(
			`${schemaKind} payload missing required field: ${field}`,
			payload,
		);
	}
	return payload[field];
}

function optionalField(payload, field, fallback) {
	if (payload && Object.hasOwn(payload, field)) {
		return payload[field];
	}
	return fallback;
}

function parseExecOutput(value) {
	const text = value === null || value === undefined ? "" : String(value);
	const exitMatch = text.match(/Exit Code:\s*(-?\d+)/i);
	const durationMatch = text.match(/Duration:\s*([\d.]+)\s*ms/i);
	const stdoutMarker = text.match(
		/\[STDOUT\]\s*([\s\S]*?)(?:\s*\[STDERR\]\s*([\s\S]*))?$/i,
	);
	const clean = (part) => {
		const normalized = String(part || "").trim();
		return normalized === "(empty)" ? "" : normalized;
	};
	if (!stdoutMarker) {
		return {
			stdout: clean(text),
			stderr: "",
			exit_code: exitMatch ? Number(exitMatch[1]) : 0,
			duration_ms: durationMatch ? Number(durationMatch[1]) : 0,
		};
	}
	return {
		stdout: clean(stdoutMarker[1]),
		stderr: clean(stdoutMarker[2]),
		exit_code: exitMatch ? Number(exitMatch[1]) : 0,
		duration_ms: durationMatch ? Number(durationMatch[1]) : 0,
	};
}

/**
 * Validators return a normalised payload (with safe fallbacks) instead of
 * throwing. The UI MUST call these on every tool result before rendering.
 * A failure here is a wire contract bug — log loud, render a fallback
 * generic card, never silently misrender.
 */
export const ToolPayloadSchemas = {
	generic(payload) {
		expectObject(payload, "generic");
		return {
			schema_kind: "generic",
			fields: { ...(payload || {}) },
		};
	},

	exec(payload) {
		expectObject(payload, "exec");
		const formatted = optionalField(
			payload,
			"output",
			optionalField(payload, "error", ""),
		);
		const parsed = parseExecOutput(formatted);
		const command = optionalField(
			payload,
			"command",
			optionalField(payload, "code_snippet", "Execution"),
		);
		return {
			schema_kind: "exec",
			command,
			stdout: optionalField(payload, "stdout", parsed.stdout),
			stderr: optionalField(payload, "stderr", parsed.stderr),
			exit_code: optionalField(payload, "exit_code", parsed.exit_code),
			duration_ms: optionalField(payload, "duration_ms", parsed.duration_ms),
			language: optionalField(
				payload,
				"language",
				payload.code_snippet ? "python" : null,
			),
		};
	},

	image(payload) {
		expectObject(payload, "image");
		return {
			schema_kind: "image",
			image_path: requireField(payload, "image_path", "image"),
			image_url: optionalField(payload, "image_url", null),
			prompt: optionalField(payload, "prompt", ""),
			alt: optionalField(payload, "alt", "Image"),
			model: optionalField(payload, "model", null),
		};
	},

	weather(payload) {
		expectObject(payload, "weather");
		if (payload.status === "location_required") {
			return {
				schema_kind: "weather",
				status: "location_required",
				location: null,
			};
		}
		const current = payload.current || {};
		const daily = optionalField(payload, "daily", []);
		return {
			schema_kind: "weather",
			temperature_c: optionalField(
				payload,
				"temperature_c",
				current.temperature_2m ?? null,
			),
			condition: optionalField(
				payload,
				"condition",
				current.condition ?? current.weather_code ?? "Unknown",
			),
			humidity_pct: optionalField(
				payload,
				"humidity_pct",
				current.relative_humidity_2m ?? null,
			),
			wind_kph: optionalField(
				payload,
				"wind_kph",
				current.wind_speed_10m ?? null,
			),
			location_label: optionalField(payload, "location_label", null),
			requested_date: optionalField(payload, "requested_date", null),
			daily: Array.isArray(daily) ? daily : [],
			icon: optionalField(payload, "icon", null),
		};
	},

	http(payload) {
		expectObject(payload, "http");
		return {
			schema_kind: "http",
			url: requireField(payload, "url", "http"),
			method: optionalField(payload, "method", "GET"),
			status_code: optionalField(payload, "status_code", 0),
			content_type: optionalField(payload, "content_type", ""),
			size_bytes: optionalField(payload, "size_bytes", 0),
			body: optionalField(payload, "body", ""),
			truncated: optionalField(payload, "truncated", false),
			image_path: optionalField(payload, "image_path", null),
		};
	},

	file_read(payload) {
		expectObject(payload, "file_read");
		return {
			schema_kind: "file_read",
			path: requireField(payload, "path", "file_read"),
			size: optionalField(payload, "size", 0),
			lines: optionalField(payload, "lines", 0),
			content: optionalField(payload, "content", ""),
			file_ext: optionalField(payload, "file_ext", ""),
		};
	},

	file_write(payload) {
		expectObject(payload, "file_write");
		return {
			schema_kind: "file_write",
			path: requireField(payload, "path", "file_write"),
			bytes_written: optionalField(payload, "bytes_written", 0),
			lines: optionalField(payload, "lines", 0),
		};
	},

	file_list(payload) {
		expectObject(payload, "file_list");
		const entries = optionalField(payload, "entries", []);
		return {
			schema_kind: "file_list",
			path: requireField(payload, "path", "file_list"),
			entries: Array.isArray(entries) ? entries : [],
			total: optionalField(payload, "total", entries.length || 0),
			directories: optionalField(payload, "directories", 0),
			files: optionalField(payload, "files", 0),
		};
	},

	file_delete(payload) {
		expectObject(payload, "file_delete");
		return {
			schema_kind: "file_delete",
			path: requireField(payload, "path", "file_delete"),
			deleted: optionalField(payload, "deleted", true),
		};
	},

	sql_query(payload) {
		expectObject(payload, "sql_query");
		return {
			schema_kind: "sql_query",
			query: requireField(payload, "query", "sql_query"),
			write_mode: optionalField(payload, "write_mode", false),
			columns: optionalField(payload, "columns", []),
			rows: optionalField(payload, "rows", []),
			row_count: optionalField(payload, "row_count", 0),
		};
	},

	memory_store(payload) {
		expectObject(payload, "memory_store");
		return {
			schema_kind: "memory_store",
			status: requireField(payload, "status", "memory_store"),
			category: optionalField(payload, "category", null),
			fact: optionalField(payload, "fact", null),
			confidence: optionalField(payload, "confidence", null),
			fact_id: optionalField(payload, "fact_id", null),
		};
	},

	memory_search(payload) {
		expectObject(payload, "memory_search");
		return {
			schema_kind: "memory_search",
			results: optionalField(payload, "results", []),
			count: optionalField(payload, "count", 0),
		};
	},

	ask_rei(payload) {
		expectObject(payload, "ask_rei");
		return {
			schema_kind: "ask_rei",
			status: requireField(payload, "status", "ask_rei"),
			conversation_id: requireField(payload, "conversation_id", "ask_rei"),
			response: optionalField(payload, "response", ""),
		};
	},
};

/**
 * Resolve a schema_kind from either the data payload (canonical) or the
 * tool name (fallback for legacy persistence rows that predate the
 * structured wire). Returns null if neither is recognisable.
 */
export function resolveSchemaKind(payload, toolName) {
	const fromData =
		payload && typeof payload === "object" ? payload.schema_kind : null;
	if (fromData && ToolPayloadSchemas[fromData]) {
		return fromData;
	}
	if (!toolName) return null;
	const alias = {
		terminal: "exec",
		bash: "exec",
		python: "exec",
		sql: "sql_query",
		imagine: "image",
		image_generate: "image",
		image_edit: "image",
		weather: "weather",
		http_request: "http",
		request: "http",
		read: "file_read",
		write: "file_write",
		ls: "file_list",
		mkdir: "file_delete",
		rm: "file_delete",
		memory_store: "memory_store",
		memory_search: "memory_search",
		ask_rei: "ask_rei",
	};
	return alias[toolName] || null;
}

/**
 * Validate a raw payload against its declared schema_kind, with a safe
 * generic fallback. Validation failures are returned structurally so the UI
 * can render a safe generic card.
 *
 * @param {object} payload - raw `data` from the wire
 * @param {string} toolName - canonical tool name (alias-resolved)
 * @returns {{schema_kind: string, normalised: object, validationError: Error|null}}
 */
export function validateToolPayload(payload, toolName) {
	const kind = resolveSchemaKind(payload, toolName);
	if (!kind) {
		return {
			schema_kind: "generic",
			normalised: ToolPayloadSchemas.generic(payload || {}),
			validationError: null,
		};
	}
	const validator = ToolPayloadSchemas[kind];
	try {
		return {
			schema_kind: kind,
			normalised: validator(payload || {}),
			validationError: null,
		};
	} catch (err) {
		return {
			schema_kind: "generic",
			normalised: ToolPayloadSchemas.generic(payload || {}),
			validationError: err,
		};
	}
}

export { ToolPayloadValidationError };

export function canonicalToolName(name) {
	if (typeof name !== "string" || !name) return "unknown";
	const aliases = {
		terminal: "exec",
		bash: "exec",
		python: "exec",
		sql: "sql_query",
		image_generate: "image",
		image_edit: "image",
		imagine: "image",
		weather: "weather",
	};
	return aliases[name] || name;
}

export function parseToolResult(payload, toolName = "") {
	const raw = payload && typeof payload === "object" ? payload : {};
	const data = raw.data && typeof raw.data === "object" ? raw.data : raw;
	const name = toolName || raw.name || "unknown";
	const validation = validateToolPayload(data, name);
	return {
		name,
		ok: raw.ok !== false,
		data,
		error: raw.error || raw.error_message || "",
		...validation,
	};
}
