import requests
import re
import json
from html import unescape


SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information, news, prices, events, or anything time-sensitive. Returns 20-30 snippet results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    }
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_DDG_URL = "https://html.duckduckgo.com/html/"


def _ddg_search(query):
    """Query DuckDuckGo HTML endpoint and extract snippet results."""
    resp = requests.post(
        _DDG_URL,
        data={"q": query},
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    results = []
    # Each result block is a <div class="result ...">
    blocks = re.findall(
        r'<div[^>]*class="[^"]*result\b[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*result\b|$)',
        html, re.DOTALL
    )

    # Fallback: try splitting by result__body if block regex didn't work
    if not blocks:
        blocks = re.findall(
            r'<div[^>]*class="[^"]*result__body[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )

    for block in blocks:
        # Title
        title_m = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

        # URL
        url_m = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"', block)
        url = ""
        if url_m:
            raw_url = unescape(url_m.group(1))
            # DuckDuckGo wraps URLs in a redirect; extract the actual URL
            uddg_m = re.search(r'[?&]uddg=([^&]+)', raw_url)
            if uddg_m:
                url = requests.utils.unquote(uddg_m.group(1))
            else:
                url = raw_url

        # Snippet
        snippet_m = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not snippet_m:
            snippet_m = re.search(r'<div[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
        snippet = ""
        if snippet_m:
            snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1))
            snippet = unescape(snippet).strip()

        if title and url:
            results.append({
                "title": unescape(title),
                "url": url,
                "snippet": snippet,
            })

        if len(results) >= 30:
            break

    return results


def execute(arguments, **kwargs):
    query = arguments.get("query", "")
    if not query:
        return json.dumps({"error": "No query provided"})

    try:
        results = _ddg_search(query)

        if not results:
            return json.dumps({"results": [], "note": "No results found"})

        return json.dumps({"results": results})

    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})
