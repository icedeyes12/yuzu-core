// Replaces the vendored UMD assets in static/vendor: marked, KaTeX,
// Highlight.js (with the runtime language set), and Mermaid are npm imports
// bundled by Vite. The window globals keep the ported modules working
// unchanged until they are migrated to direct imports.
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import "highlight.js/styles/tomorrow-night-blue.css";
import katex from "katex";
import renderMathInElement from "katex/contrib/auto-render";
import "katex/dist/katex.min.css";
import { marked } from "marked";
import mermaid from "mermaid";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("python", python);

window.marked = marked;
window.hljs = hljs;
window.katex = katex;
window.renderMathInElement = renderMathInElement;
window.mermaid = mermaid;
