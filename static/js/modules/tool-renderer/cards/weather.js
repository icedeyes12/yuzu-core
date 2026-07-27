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
		window.RuntimeIconRenderer?.render(iconName, {
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
	const {
		temperature_c,
		condition,
		humidity_pct,
		wind_kph,
		location_label,
		daily,
	} = normalised;
	const windRow =
		wind_kph === null || wind_kph === undefined
			? ""
			: `<div class="weather-card__metric"><span class="weather-card__metric-label">Wind</span><span class="weather-card__metric-value">${escapeHtml(Number(wind_kph).toFixed(1))} km/h</span></div>`;

	return `<div class="tool-card tool-card--weather"><div class="weather-card"><div class="weather-card__header"><div><div class="weather-card__title">${escapeHtml(location_label || "Weather")}</div><div class="weather-card__condition">${escapeHtml(condition)}</div></div><div class="weather-card__icon" aria-hidden="true">${pickIcon(condition)}</div></div><div class="weather-card__hero"><div class="weather-card__temp">${escapeHtml(Number(temperature_c).toFixed(1))}°C</div><div class="weather-card__metrics"><div class="weather-card__metric"><span class="weather-card__metric-label">Humidity</span><span class="weather-card__metric-value">${escapeHtml(Number(humidity_pct).toFixed(0))}%</span></div>${windRow}</div></div>${renderDailyForecast(daily)}</div></div>`;
}

export { renderWeatherCard };
