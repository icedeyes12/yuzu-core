import requests
import re
import json
from html import unescape


SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information, news, prices, events, or anything time-sensitive.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "freshness": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "Limit results to recent content. 'day' = last 24h, 'week' = last 7 days, 'month' = last 30 days. Omit for no time filter."
                }
            },
            "required": ["query"]
        }
    }
}


def _fetch_page_content(url, max_chars=3000):
    """Fetch and extract main text content from a URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        html = resp.text

        # Strip script/style tags
        html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Strip all HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)
        text = unescape(text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars] if text else ""
    except Exception:
        return ""


def execute(arguments, **kwargs):
    query = arguments.get("query", "")
    freshness = arguments.get("freshness", "")
    if not query:
        return json.dumps({"error": "No query provided"})

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        }

        params = {"q": query}
        # DuckDuckGo time filter: d = day, w = week, m = month
        freshness_map = {"day": "d", "week": "w", "month": "m"}
        if freshness in freshness_map:
            params["df"] = freshness_map[freshness]

        resp = requests.get(
            "https://duckduckgo.com/html/",
            params=params,
            headers=headers,
            timeout=15
        )
        resp.raise_for_status()
        html = resp.text

        results = []
        # Parse result blocks
        blocks = re.findall(
            r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for url, title_html, snippet_html in blocks[:5]:
            title = unescape(re.sub(r'<[^>]+>', '', title_html)).strip()
            snippet = unescape(re.sub(r'<[^>]+>', '', snippet_html)).strip()
            if title and snippet:
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url
                })

        if not results:
            return json.dumps({"results": [], "note": "No results found"})

        # Fetch page content from top 3 results for concrete data
        for r in results[:3]:
            page_text = _fetch_page_content(r["url"])
            if page_text:
                r["page_text"] = page_text

        return json.dumps({"results": results})

    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})
