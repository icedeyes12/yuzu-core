import requests
import json
from html import unescape
from urllib.parse import unquote

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information, news, prices, events, or anything time-sensitive. Returns 15-20 snippet results.",
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
_MAX_RESULTS = 20


def _extract_ddg_url(raw_href):
    """Extract real URL from DuckDuckGo redirect wrapper."""
    if not raw_href:
        return ""
    raw_href = unescape(raw_href)
    if "uddg=" in raw_href:
        for part in raw_href.split("&"):
            if part.startswith("uddg=") or part.startswith("?uddg="):
                return unquote(part.split("=", 1)[1])
    return raw_href


def _ddg_search(query):
    """Query DuckDuckGo HTML endpoint and extract results with BeautifulSoup."""
    resp = requests.post(
        _DDG_URL,
        data={"q": query},
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()

    if BeautifulSoup is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for div in soup.select("div.result, div.results_links"):
        # Title + URL from the main result link
        link_tag = div.select_one("a.result__a")
        if not link_tag:
            continue

        title = link_tag.get_text(strip=True)
        url = _extract_ddg_url(link_tag.get("href", ""))

        if not title or not url:
            continue

        # Snippet
        snippet_tag = div.select_one("a.result__snippet") or div.select_one("div.result__snippet")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
        })

        if len(results) >= _MAX_RESULTS:
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
