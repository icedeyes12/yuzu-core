import { bootApp } from "../main.js";

async function init() {
	await bootApp({ page: "about" });
}

init();
