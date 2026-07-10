"""
competitor_data_tool.py (multi-brand)

Pulls recent news coverage of launches, promotions, and pricing moves for
one or more brands using NewsAPI.org's free tier, grouped by brand so you
can see relative press/PR activity across a portfolio or competitive set.

For deeper competitive intel (SKU-level pricing, promo calendars, shelf
data), pair this with a retail intelligence source like Numerator,
Stackline, or Edge by Ascential -- swap the fetch logic here, keep the
CodedTool interface the same.

Setup:
    pip install requests
    Get a free API key at https://newsapi.org/register
    Set environment variable: NEWSAPI_KEY
"""

import os
from typing import Any, Dict, List,Union
import requests
from neuro_san.interfaces.coded_tool import CodedTool

class CompetitorDataTool(CodedTool):
    """
    CodedTool that returns recent news articles about launches, promotions,
    and pricing activity for each brand in the given list.
    """

    NEWSAPI_URL = "https://newsapi.org/v2/everything"

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        brands = self._normalize_brands(args)
        page_size = int(args.get("page_size", 20))

        if not brands:
            return {"error": "Missing required 'brands' argument (list of brand/category names)."}

        api_key = os.environ.get("NEWSAPI_KEY")
        if not api_key:
            return {"error": "NEWSAPI_KEY environment variable not set."}

        articles_by_brand: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for brand in brands:
            query = f'{brand} AND (launch OR promotion OR pricing OR "market share")'
            try:
                response = requests.get(
                    self.NEWSAPI_URL,
                    params={
                        "q": query,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "pageSize": page_size,
                        "apiKey": api_key,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                articles_by_brand[brand] = self._extract_articles(data.get("articles", []))
            except requests.RequestException as e:
                errors.append(f"{brand}: {str(e)}")
                articles_by_brand[brand] = []

        activity_ranking = sorted(
            articles_by_brand.items(), key=lambda kv: len(kv[1]), reverse=True
        )

        result = {
            "brands": brands,
            "articles_by_brand": articles_by_brand,
            "press_activity_ranking": [b for b, _ in activity_ranking],
            "source": "NewsAPI.org",
        }
        if errors:
            result["errors"] = errors

        # Stash structured counts so generate_dashboard can use real numbers.
        sly_data["last_press_activity"] = {b: len(a) for b, a in articles_by_brand.items()}

        return result

    @staticmethod
    def _normalize_brands(args: Dict[str, Any]) -> List[str]:
        brands = args.get("brands")
        if brands:
            return list(brands)
        scope = args.get("scope")
        return [scope] if scope else []

    @staticmethod
    def _extract_articles(raw_articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        extracted = []
        for a in raw_articles:
            extracted.append(
                {
                    "title": a.get("title"),
                    "source": (a.get("source") or {}).get("name"),
                    "published_at": a.get("publishedAt"),
                    "description": a.get("description"),
                    "url": a.get("url"),
                }
            )
        return extracted
    
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method because it's quick, non-blocking.
        """
        return self.invoke(args, sly_data)