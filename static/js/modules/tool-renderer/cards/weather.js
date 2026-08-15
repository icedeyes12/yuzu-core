import { renderRuntimeIcon } from "../../../runtime-icon-renderer.js";
import { escapeHtml } from "../dom-utils.js";

const WEATHER_ICONS = Object.freeze({
	"Clear sky": "weather-sunny",
	"Mainly clear": "weather-partly-cloudy",
	"Partly cloudy": "weather-partly-cloudy",
	Overcast: "weather-cloudy",
	Fog: "weather-fog",
	"Light drizzle": "weather-rain",
	"Moderate drizzle": "weather-rain",
	"Dense drizzle": "weather-rain",
	"Slight rain": "weather-rain",
	"Moderate rain": "weather-rain",
	"Heavy rain": "weather-rain",
	"Rain showers": "weather-rain",
	Thunderstorm: "weather-storm",
	"Slight snow": "weather-snow",
	"Moderate snow": "weather-snow",
	"Heavy snow": "weather-snow",
});

function pickIcon(condition) {
	const iconName = WEATHER_ICONS[condition] || "weather-partly-cloudy";
	return (
		renderRuntimeIcon(iconName, {
			size: 32,
			className: "weather-icon",
		}) || ""
	);
}

function displayValue(value, suffix = "") {
	return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

function formatDay(value) {
	const parsed = new Date(`${value}T12:00:00`);
	return Number.isNaN(parsed.getTime())
		? value
		: parsed.toLocaleDateString(undefined, {
				weekday: "short",
				month: "short",
				day: "numeric",
			});
}

function renderDailyForecast(rows) {
	if (!rows.length) return "";
	return `<div class="weather-card__forecast">${rows
		.map(
			(day) =>
				`<div class="weather-card__day"><div class="weather-card__day-name">${escapeHtml(formatDay(day.date))}</div><div class="weather-card__day-icon" aria-hidden="true">${pickIcon(day.condition)}</div><div class="weather-card__day-temp">${escapeHtml(displayValue(day.temperature_2m_min, "°"))} / ${escapeHtml(displayValue(day.temperature_2m_max, "°C"))}</div><div class="weather-card__day-rain">${escapeHtml(displayValue(day.precipitation_probability_max, "% rain"))}</div></div>`,
		)
		.join("")}</div>`;
}

function renderWeatherCard(normalised) {
	if (normalised.status === "location_required") {
		return `<div class="tool-card tool-card--weather"><div class="weather-card"><div class="weather-card__title">Weather location belum dikonfigurasi.</div><button type="button" class="button" data-action="open-settings">Configure location</button></div></div>`;
	}
	const {
		temperature_c,
		condition,
		humidity_pct,
		wind_kph,
		location_label,
		daily,
	} = normalised;
	const displayLocation =
		typeof location_label === "string" && location_label.trim()
			? location_label.trim()
			: "Configured location";
	const windRow =
		wind_kph === null || wind_kph === undefined
			? ""
			: `<div class="weather-card__metric"><span class="weather-card__metric-label">Wind</span><span class="weather-card__metric-value">${escapeHtml(Number(wind_kph).toFixed(1))} km/h</span></div>`;

	const temperature = displayValue(temperature_c, "°C");
	const humidity = displayValue(humidity_pct, "%");
	return `<div class="tool-card tool-card--weather"><div class="weather-card"><div class="weather-card__header"><div><div class="weather-card__title">${escapeHtml(displayLocation)}</div><div class="weather-card__condition">${escapeHtml(condition)}</div></div><div class="weather-card__icon" aria-hidden="true">${pickIcon(condition)}</div></div><div class="weather-card__hero"><div class="weather-card__temp">${escapeHtml(temperature)}</div><div class="weather-card__metrics"><div class="weather-card__metric"><span class="weather-card__metric-label">Humidity</span><span class="weather-card__metric-value">${escapeHtml(humidity)}</span></div>${windRow}</div></div>${renderDailyForecast(daily)}</div></div>`;
}

export { renderWeatherCard };
