// FILE: static/js/modules/tool-renderer/cards/weather.js
// DESCRIPTION: Weather card — renders strictly from validated structured
// payload. No accordion, no markdown parsing.

import { escapeHtml } from "../dom-utils.js";

const WEATHER_ICONS = {
	clear: "☀️",
	sunny: "☀️",
	cloudy: "☁️",
	overcast: "☁️",
	rain: "🌧️",
	rainy: "🌧️",
	drizzle: "🌦️",
	thunderstorm: "⛈️",
	snow: "❄️",
	snowy: "❄️",
	fog: "🌫️",
	foggy: "🌫️",
	mist: "🌫️",
	wind: "💨",
	windy: "💨",
};

function pickIcon(icon, condition) {
	if (icon && typeof icon === "string") return icon;
	const key = String(condition || "")
		.toLowerCase()
		.trim();
	return WEATHER_ICONS[key] || "🌤️";
}

function renderWeatherCard(normalised) {
	const {
		temperature_c,
		condition,
		humidity_pct,
		wind_kph,
		location_label,
		icon,
	} = normalised;

	const iconChar = pickIcon(icon, condition);
	const title = location_label || "Weather";
	const windRow =
		wind_kph === null || wind_kph === undefined
			? ""
			: `<div class="weather-card__metric"><span class="weather-card__metric-label">Wind</span><span class="weather-card__metric-value">${escapeHtml(
					Number(wind_kph).toFixed(1),
				)} kph</span></div>`;

	return [
		`<div class="tool-card tool-card--weather">`,
		`<div class="weather-card">`,
		`<div class="weather-card__hero">`,
		`<div class="weather-card__icon" aria-hidden="true">${iconChar}</div>`,
		`<div class="weather-card__temp">${escapeHtml(
			Number(temperature_c).toFixed(1),
		)}°C</div>`,
		`</div>`,
		`<div class="weather-card__details">`,
		`<div class="weather-card__title">${escapeHtml(title)}</div>`,
		`<div class="weather-card__condition">${escapeHtml(condition)}</div>`,
		`<div class="weather-card__metrics">`,
		`<div class="weather-card__metric"><span class="weather-card__metric-label">Humidity</span><span class="weather-card__metric-value">${escapeHtml(
			Number(humidity_pct).toFixed(0),
		)}%</span></div>`,
		windRow,
		`</div>`,
		`</div>`,
		`</div>`,
		`</div>`,
	].join("");
}

export { renderWeatherCard };
