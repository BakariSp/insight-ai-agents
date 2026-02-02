import requests
from skills.base import BaseSkill


class WebSearchSkill(BaseSkill):
    """Skill for searching the web using Brave Search API."""

    name = "web_search"
    description = "Search the web for current information. Returns top search results with titles, URLs, and snippets."

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 20).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def execute(self, query: str, count: int = 5) -> str:
        if not self.api_key:
            return "Error: Brave Search API key not configured."

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": min(count, 20)}

        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            return f"Search failed: {e}"

        results = data.get("web", {}).get("results", [])
        if not results:
            return "No results found."

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. [{r.get('title', '')}]({r.get('url', '')})")
            if desc := r.get("description"):
                lines.append(f"   {desc}")
        return "\n".join(lines)
