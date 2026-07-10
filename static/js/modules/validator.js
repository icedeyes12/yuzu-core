/**
 * FILE: static/js/modules/validator.js
 * DESCRIPTION: Strict runtime payload validation before UI rendering
 */

/**
 * Validates and normalizes ToolResultEvent payloads
 * @param {string|Object} rawPayload
 * @returns {Object} Normalized object guaranteed to have specific keys
 */
export function validateToolResult(rawPayload) {
    let parsed = {};

    // 1. Parse JSON safely
    if (typeof rawPayload === 'string') {
        try {
            parsed = JSON.parse(rawPayload);
        } catch (e) {
            console.warn("[Validator] Failed to parse raw tool payload as JSON", e);
            // Fallback for completely malformed strings
            return {
                name: "unknown",
                ok: false,
                data: { raw: rawPayload },
                error: "Malformed payload format."
            };
        }
    } else if (typeof rawPayload === 'object' && rawPayload !== null) {
        parsed = rawPayload;
    }

    // 2. Normalize Schema
    const normalized = {
        name: typeof parsed.name === 'string' ? parsed.name : "unknown",
        ok: typeof parsed.ok === 'boolean' ? parsed.ok : true,
        data: typeof parsed.data === 'object' && parsed.data !== null ? parsed.data : {},
        error: typeof parsed.error === 'string' ? parsed.error : "",
        // Derived safe string output if components still want to render raw fallback
        rawString: typeof rawPayload === 'string' ? rawPayload : JSON.stringify(parsed, null, 2)
    };

    return normalized;
}