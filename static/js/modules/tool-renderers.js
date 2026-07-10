/**
 * FILE: static/js/modules/tool-renderers.js
 * DESCRIPTION: Component registry mapping backend tools to specific frontend UI representations.
 * 
 * Rules:
 * - No data patching here. Data should be normalized by validator.js
 * - Return raw HTML strings
 * - For unrecognized tools, fall back to DefaultRenderer
 */

export const ToolRenderers = {
    // -------------------------------------------------------------
    // TERMINAL & FILESYSTEM
    // -------------------------------------------------------------
    terminal: (data) => {
        const output = data.output || "(empty)";
        const exitCode = data.exit_code ?? 0;
        const duration = data.duration_ms ?? 0;

        return `
        <div class="terminal-card" style="font-family: monospace; background: #0b0f19; color: #e2e8f0; padding: 12px; border-radius: 6px; overflow-x: auto; border: 1px solid rgba(255,255,255,0.1);">
            <div style="color: #4ade80; margin-bottom: 8px;">$ ${data.command || "command"}</div>
            <pre style="margin: 0; white-space: pre-wrap; font-size: 0.9em; line-height: 1.4;">${output}</pre>
            <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); color: ${exitCode === 0 ? '#4ade80' : '#f87171'}; font-size: 0.85em; display: flex; justify-content: space-between;">
                <span>Exit: ${exitCode}</span>
                <span style="color: #94a3b8;">${duration}ms</span>
            </div>
        </div>`;
    },

    read: (data) => {
        return `
        <div class="file-card" style="background: rgba(255,255,255,0.03); border-radius: 6px; padding: 10px; border: 1px solid rgba(255,255,255,0.05);">
            <div style="font-family: monospace; font-size: 0.85em; color: var(--accent-primary, #3b82f6); margin-bottom: 8px;">📄 ${data.path || 'unknown file'}</div>
            <pre style="margin: 0; white-space: pre-wrap; font-size: 0.9em; max-height: 300px; overflow-y: auto; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">${data.content || '(empty)'}</pre>
        </div>`;
    },

    write: (data) => {
        return `
        <div class="file-card" style="background: rgba(255,255,255,0.03); border-radius: 6px; padding: 10px; border: 1px solid rgba(255,255,255,0.05);">
            <div style="font-family: monospace; font-size: 0.85em; color: #4ade80; margin-bottom: 4px;">✍️ Wrote file: ${data.path || 'unknown'}</div>
            <div style="font-size: 0.85em; color: #94a3b8;">Status: ${data.status || 'success'}</div>
        </div>`;
    },

    // -------------------------------------------------------------
    // MULTIMEDIA & WEATHER
    // -------------------------------------------------------------
    weather: (data) => {
        if (!data.current) return ToolRenderers.default(data);
        
        const current = data.current;
        const temp = current.temperature_2m;
        const humidity = current.relative_humidity_2m;
        const code = current.weather_code;

        let iconName = "cloud";
        if (code <= 1) iconName = "sun";
        else if (code <= 3) iconName = "cloud-sun";
        else if (code <= 49) iconName = "cloud-fog";
        else if (code <= 69) iconName = "cloud-rain";
        else if (code <= 79) iconName = "cloud-snow";
        else if (code <= 99) iconName = "cloud-lightning";

        const iconUrl = `https://unpkg.com/lucide-static@0.344.0/icons/${iconName}.svg`;

        return `
        <div class="weather-card" style="padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px; display: flex; align-items: center; gap: 16px;">
            <div style="width: 48px; height: 48px; background-color: var(--accent-primary, #3b82f6); -webkit-mask: url('${iconUrl}') no-repeat center; mask: url('${iconUrl}') no-repeat center; -webkit-mask-size: contain; mask-size: contain;"></div>
            <div>
                <div style="font-size: 1.6rem; font-weight: bold; line-height: 1;">${temp}°C</div>
                <div style="opacity: 0.7; font-size: 0.9em; margin-top: 4px;">Humidity: ${humidity}%</div>
            </div>
        </div>`;
    },

    image_generate: (data) => {
        if (!data.image_path) return ToolRenderers.default(data);

        let imgPath = data.image_path.replace(/^\/+/, "");
        if (!imgPath.startsWith("static/")) {
            imgPath = imgPath.startsWith("generated_images/") ? `static/${imgPath}` : imgPath;
        }
        const encodedPath = encodeURI(`/${imgPath}`);

        return `
        <div class="image-generate-card" style="border-radius: 8px; overflow: hidden; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05);">
            <img src="${encodedPath}" alt="Generated Image" style="width: 100%; height: auto; display: block;">
            <div style="padding: 10px 12px; font-size: 0.85em; color: rgba(255,255,255,0.7); display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.02);">
                <div style="display: flex; flex-direction: column; gap: 2px;">
                    <span style="font-weight: 500; color: #fff;">${data.prompt || 'Generated Image'}</span>
                    <span style="font-size: 0.9em; opacity: 0.7;">Model: ${data.model || 'AI'}</span>
                </div>
                <a href="${encodedPath}" target="_blank" style="color: var(--accent-primary, #3b82f6); text-decoration: none; padding: 4px 8px; background: rgba(59, 130, 246, 0.1); border-radius: 4px;">Open</a>
            </div>
        </div>`;
    },
    
    // Alias for imagine
    imagine: (data) => ToolRenderers.image_generate(data),

    // -------------------------------------------------------------
    // FALLBACKS
    // -------------------------------------------------------------
    default: (data) => {
        return `<pre style="white-space: pre-wrap; font-size: 0.85em; margin: 0; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; overflow-x: auto; color: #cbd5e1;">${JSON.stringify(data, null, 2)}</pre>`;
    },
    
    error: (msg) => {
        return `<div style="color: #f87171; background: rgba(248,113,113,0.1); padding: 10px; border-radius: 6px; font-size: 0.9em; border: 1px solid rgba(248,113,113,0.2);">${msg}</div>`;
    }
};
