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

SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://search.mdosch.de",
    "https://searx.tiekoetter.com",
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json",
}


def _fetch_page_content(url, max_chars=4000):
    """Fetch and extract visible text from a URL."""
    try:
        resp = requests.get(url, headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=10)
        resp.raise_for_status()
        html = resp.text

        html = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', '', html,
                       flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', html)
        text = unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars] if text else ""
    except Exception:
        return ""


def _extract_numbers(text):
    """Extract price-like and numeric patterns from text."""
    patterns = [
        r'(?:Rp\.?\s*[\d.,]+)',
        r'(?:IDR\s*[\d.,]+)',
        r'(?:\$\s*[\d.,]+)',
        r'(?:USD\s*[\d.,]+)',
        r'(?:[\d.,]+\s*(?:ribu|juta|rb|jt))',
    ]
    numbers = []
    for pat in patterns:
        numbers.extend(re.findall(pat, text, re.IGNORECASE))
    return numbers[:10]


def _searxng_query(query, freshness=""):
    """Query SearXNG JSON API, trying multiple instances."""
    params = {
        "q": query,
        "format": "json",
        "language": "id-ID",
        "categories": "general",
    }
    if freshness == "day":
        params["time_range"] = "day"
    elif freshness == "week":
        params["time_range"] = "week"
    elif freshness == "month":
        params["time_range"] = "month"

    last_err = None
    for instance in SEARXNG_INSTANCES:
        try:
            resp = requests.get(
                f"{instance}/search",
                params=params,
                headers=_HEADERS,
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_results = data.get("results", [])
            if raw_results:
                return raw_results
        except Exception as e:
            last_err = e
            continue

    raise last_err or RuntimeError("All SearXNG instances failed")


def execute(arguments, **kwargs):
    query = arguments.get("query", "")
    freshness = arguments.get("freshness", "")
    if not query:
        return json.dumps({"error": "No query provided"})

    try:
        raw_results = _searxng_query(query, freshness)

        results = []
        for item in raw_results[:5]:
            title = item.get("title", "").strip()
            content = item.get("content", "").strip()
            url = item.get("url", "").strip()
            if title and url:
                results.append({
                    "title": title,
                    "content": content,
                    "url": url,
                })

        if not results:
            return json.dumps({"results": [], "note": "No results found"})

        # Deep fetch top 3 pages for concrete data
        pages = []
        for r in results[:3]:
            page_text = _fetch_page_content(r["url"])
            if page_text:
                nums = _extract_numbers(page_text)
                page_entry = {"url": r["url"], "text": page_text}
                if nums:
                    page_entry["extracted_numbers"] = nums
                pages.append(page_entry)

        return json.dumps({"results": results, "pages": pages})

    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})
