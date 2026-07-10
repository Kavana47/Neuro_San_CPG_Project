"""
feedback_data_tool.py (multi-brand, DuckDuckGo-based)

Pulls customer-feedback-flavored text for each brand by web-searching for
review and complaint content (blogs, forums, review sites, news mentions)
via DuckDuckGo, which requires NO API key and NO account/OAuth setup at
all -- the simplest option to get running of the three we've tried
(Reddit needed app credentials, YouTube needed a Cloud API key + quota).

Trade-off to know: DuckDuckGo returns search-result SNIPPETS (short
excerpts), not full review text, and reflects whatever pages rank for the
query rather than a curated review corpus. It's a reasonable free proxy for
sentiment/theme direction, not a substitute for a real review platform.

For production use, replace or supplement this with a real review source:
Bazaarvoice, Yotpo, or a retailer review export (Amazon Vine/Seller Central,
Walmart Marketplace, etc.) -- swap `_fetch_from_web_search()` for a
`_fetch_from_reviews_platform()` method, keep the CodedTool interface the
same.

Setup:
    pip install ddgs -- this tool tries both import paths automatically)
No API key or account required.
"""

from typing import Any, Dict, List, Union
from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san_studio.coded_tools.ddgs_search import DdgsSearch


#from ddgs import DDGS


class FeedbackDataTool(CodedTool):
    """
    CodedTool that returns web-search-derived feedback snippets (reviews,
    complaints, opinion pieces) for each brand in the given list, grouped by
    brand, plus a relative share-of-voice metric based on result volume.
    """

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        brands = self._normalize_brands(args)
        #country = args.get("country", "India")
        #sources = args.get("sources", "web search (DuckDuckGo)")
        limit_per_brand = int(args.get("limit_per_brand", 25))
        
        if not brands:
            return {"error": "Missing required 'brands' argument (list of brand/product names)."}

        feedback_by_brand: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for brand in brands:
            try:
                feedback_by_brand[brand] = self._fetch_from_web_search(brand, limit_per_brand)
            #    results: List[Dict[str, Any]] = []
            #    queries = [f"{brand} reviews", f"{brand} complaints"]
            #    per_query_limit = max(limit_per_brand // len(queries), 5)
            #    for query in queries:
            #        if len(results) >= limit_per_brand:
            #            break
            #        intermediate = DdgsSearch().invoke({"query": query, "max_results": per_query_limit}, sly_data=sly_data)                               
            #        for hit in intermediate:
            #            if len(results) >= limit_per_brand:
            #                break
            #            snippet = hit.get("body", "")
            #            if not snippet:
            #                continue
            #            results.append(
            #                {
            #                    "brand": brand,
            #                    "query": query,
            #                    "title": hit.get("title", ""),
            #                    "text": snippet[:1000],
            #                    "url": hit.get("href", ""),
            #                }
            #            )
            #    feedback_by_brand[brand] = results
            
            except Exception as e:
                errors.append(f"{brand}: {str(e)}")
                feedback_by_brand[brand] = []

        total_results = sum(len(v) for v in feedback_by_brand.values())
        share_of_voice = {
            brand: round(len(results) / total_results, 3) if total_results else 0.0
            for brand, results in feedback_by_brand.items()
        }

        # Store texts grouped by brand in sly_data so sentiment_tool can
        # pick them up directly without re-fetching.
        sly_data["last_feedback_texts_by_brand"] = {
            brand: [r["text"] for r in results] for brand, results in feedback_by_brand.items()
        }
        sly_data["last_share_of_voice"] = share_of_voice

        result = {
            "brands": brands,
            "feedback_by_brand": feedback_by_brand,
            "share_of_voice_by_result_count": share_of_voice,
            "caveat": (
                "Feedback text is drawn from web-search snippets (reviews, complaints, "
                "opinion content), not a curated review database -- treat sentiment as "
                "directional, not definitive."
            ),
        }
        if errors:
            result["errors"] = errors
        return result

    @staticmethod
    def _normalize_brands(args: Dict[str, Any]) -> List[str]:
        brands = args.get("brands")
        if brands:
            return list(brands)
        scope = args.get("scope")
        return [scope] if scope else []

    @staticmethod
    def _fetch_from_web_search(brand: str, limit: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        queries = [f"{brand} reviews", f"{brand} complaints"]
        per_query_limit = max(limit // len(queries), 5)

        #with DDGS() as ddgs:
        for query in queries:
                if len(results) >= limit:
                    break
                #hits = ddgs.text(query, max_results=per_query_limit)
                hits = DdgsSearch().invoke({"query": query, "max_results": per_query_limit}, sly_data={})
                for hit in hits:
                    if len(results) >= limit:
                        break
                    snippet = hit.get("body", "")
                    if not snippet:
                        continue
                    results.append(
                        {
                            "brand": brand,
                            "query": query,
                            "title": hit.get("title", ""),
                            "text": snippet[:1000],
                            "url": hit.get("href", ""),
                        }
                    )

        return results
    
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method because it's quick, non-blocking.
        """
        return self.invoke(args, sly_data) 