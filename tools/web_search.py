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
                }
            },
            "required": ["query"]
        }
    }
}


def execute(arguments, **kwargs):
    query = arguments.get("query", "")
    if not query:
        return json.dumps({"error": "No query provided"})

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        }
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
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

        return json.dumps({"results": results})

    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})
