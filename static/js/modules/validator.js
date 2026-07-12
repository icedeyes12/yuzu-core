/**
 * FILE: static/js/modules/validator.js
 * DESCRIPTION: Strict runtime payload validation before UI rendering
 */

import { ToolRenderers } from "./tool-renderers.js";

/**
 * Validates and normalizes ToolResultEvent payloads
 * @param {string|Object} rawPayload
 * @returns {Object} Normalized object guaranteed to have specific keys
 */
export function validateToolResult(rawPayload) {
    let parsed = {};

    if (typeof rawPayload === 'string') {
        try {
            parsed = JSON.parse(rawPayload);
        } catch (e) {
            console.warn("[Validator] Failed to parse raw tool payload as JSON");
            return {
                name: "unknown",
                ok: false,
                data: { raw: rawPayload },
                error: "Malformed payload format.",
                html: ToolRenderers.error("Malformed payload format. The backend did not return valid JSON.")
            };
        }
    } else if (typeof rawPayload === 'object' && rawPayload !== null) {
        parsed = rawPayload;
    }

    const name = typeof parsed.name === 'string' ? parsed.name : "unknown";
    const ok = typeof parsed.ok === 'boolean' ? parsed.ok : true;
    const data = typeof parsed.data === 'object' && parsed.data !== null ? parsed.data : {};
    const error = typeof parsed.error === 'string' ? parsed.error : "";
    
    // Generate HTML using Component Registry immediately after validation
    let html;
    if (!ok && error) {
        html = ToolRenderers.error(error);
    } else {
        const renderFn = ToolRenderers[name] || ToolRenderers.default;
        html = renderFn(data);
    }

    return { name, ok, data, error, html };
}