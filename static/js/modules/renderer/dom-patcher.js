import { cancelFenceAsyncWork, cleanupFenceBlocks } from "../fence-registry.js";

export function patchContentContainer(root, html) {
	const desired = document.createElement("div");
	desired.innerHTML = html;
	assignFenceKeys(root);
	assignFenceKeys(desired);
	patchChildren(root, desired);
}

function assignFenceKeys(root) {
	const counts = new Map();
	for (const el of root.querySelectorAll("[data-fence-lang]")) {
		const lang = el.dataset.fenceLang || "__unknown__";
		const index = (counts.get(lang) || 0) + 1;
		counts.set(lang, index);
		el.dataset.fenceKey = `${lang}:${index}`;
	}
}

function patchChildren(currentParent, desiredParent) {
	const keyedCurrent = new Map(
		[...currentParent.childNodes]
			.filter((node) => node.nodeType === Node.ELEMENT_NODE)
			.map((node) => [node.dataset.fenceKey, node])
			.filter(([key]) => key),
	);
	const used = new Set();
	let cursor = currentParent.firstChild;
	for (const desiredNode of desiredParent.childNodes) {
		const key =
			desiredNode.nodeType === Node.ELEMENT_NODE
				? desiredNode.dataset.fenceKey
				: null;
		let currentNode = key ? keyedCurrent.get(key) : null;
		if (currentNode && !used.has(currentNode)) {
			if (currentNode !== cursor)
				currentParent.insertBefore(currentNode, cursor);
			used.add(currentNode);
			patchNode(currentNode, desiredNode);
			cursor = currentNode.nextSibling;
			continue;
		}
		if (
			!key &&
			cursor &&
			!used.has(cursor) &&
			sameNodeType(cursor, desiredNode)
		) {
			currentNode = cursor;
			used.add(currentNode);
			patchNode(currentNode, desiredNode);
			cursor = currentNode.nextSibling;
			continue;
		}
		currentNode = desiredNode.cloneNode(true);
		currentParent.insertBefore(currentNode, cursor);
		used.add(currentNode);
		cursor = currentNode.nextSibling;
	}
	for (const node of [...currentParent.childNodes]) {
		if (!used.has(node)) {
			cancelFenceAsyncWork(node);
			cleanupFenceBlocks(node);
			node.remove();
		}
	}
}

function sameNodeType(current, desired) {
	if (current.nodeType !== desired.nodeType) return false;
	return (
		current.nodeType !== Node.ELEMENT_NODE ||
		current.nodeName === desired.nodeName
	);
}

function patchNode(current, desired) {
	if (current.nodeType === Node.TEXT_NODE) {
		if (current.nodeValue !== desired.nodeValue)
			current.nodeValue = desired.nodeValue;
		return;
	}
	if (current.nodeType !== Node.ELEMENT_NODE) return;
	const isActivatedFence =
		current.matches("[data-fence-lang]") && current.dataset.fenceActivated;
	if (
		isActivatedFence &&
		current.dataset.fenceSource !== desired.dataset.fenceSource
	) {
		cancelFenceAsyncWork(current);
		cleanupFenceBlocks(current);
		delete current.dataset.fenceActivated;
	}
	patchNodeAttributes(current, desired);
	if (current.matches("[data-fence-lang]") && current.dataset.fenceActivated)
		return;
	patchChildren(current, desired);
}

function patchNodeAttributes(current, desired) {
	for (const attribute of [...current.attributes]) {
		if (
			!desired.hasAttribute(attribute.name) &&
			attribute.name !== "data-fence-activated"
		)
			current.removeAttribute(attribute.name);
	}
	for (const attribute of desired.attributes) {
		if (
			attribute.name !== "data-fence-activated" &&
			current.getAttribute(attribute.name) !== attribute.value
		)
			current.setAttribute(attribute.name, attribute.value);
	}
}
