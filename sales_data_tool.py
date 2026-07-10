"""
Market trend signal using Google Trends (via pytrends) as a free proxy for
consumer demand/interest, across one or more brands at once. Requesting
multiple brands in a single pytrends payload returns interest NORMALIZED
relative to each other, which is what makes cross-brand comparison meaningful
(fetching each brand separately would each be normalized to its own 0-100
scale and NOT be comparable).

Google Trends caps comparative payloads at 5 terms. If more than 5 brands are
given, this tool batches them, always including the FIRST brand in every
batch as a common anchor so relative scale stays roughly comparable across
batches (still an approximation -- flag this to the user for >5 brands).

For production use with real POS/sales data, swap this out for a connector to
Nielsen IQ, Circana (IRI), or your internal sales data warehouse -- the
CodedTool interface (invoke) stays the same, only the data-fetching logic
inside changes.

Setup:
    pip install pytrends
No API key required (pytrends scrapes the public Google Trends UI, so it can
be rate-limited -- add retry/backoff for production use).
"""


from typing import Any
from typing import Dict,List
from typing import Union
from pytrends.request import TrendReq
from neuro_san.interfaces.coded_tool import CodedTool



MAX_TERMS_PER_REQUEST = 5

# Common country name -> Google Trends geo code. Extend as needed.
COUNTRY_GEO_CODES = {
    "india": "IN",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "worldwide": "",
    "global": "",
}
DEFAULT_COUNTRY = "India"
 

class SalesDataTool(CodedTool):
    """
    CodedTool that returns interest-over-time and relative momentum for one
    or more brands, standing in for sales trend data.
    """

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        brands = self._normalize_brands(args)
        time_range = args.get("time_range", "today 12-m")
        country = args.get("country", DEFAULT_COUNTRY)
        geo = COUNTRY_GEO_CODES.get(country.strip().lower(), "")

        if not brands:
            return {"error": "Missing required 'brands' argument (list of brand/product names)."}

        timeframe = self._normalize_timeframe(time_range)
        batches = self._batch_brands(brands)

        try:
            pytrends = TrendReq(hl="en-US", tz=330 if geo == "IN" else 360)
        except Exception as e:
            return {"error": f"Failed to initialize Google Trends client: {str(e)}"}

        per_brand_results: Dict[str, Any] = {}
        errors: List[str] = []

        for batch in batches:
            try:
                pytrends.build_payload(batch, timeframe=timeframe)
                interest_over_time = pytrends.interest_over_time()

                if interest_over_time.empty:
                    for brand in batch:
                        per_brand_results.setdefault(
                            brand, {"note": "No Google Trends data found."}
                        )
                    continue

                for brand in batch:
                    if brand not in interest_over_time.columns:
                        per_brand_results[brand] = {"note": "No data returned for this brand."}
                        continue
                    series = interest_over_time[brand].to_dict()
                    per_brand_results[brand] = {
                        "interest_over_time": series,
                        "trend_direction": self._trend_direction(list(series.values())),
                        "avg_interest": round(sum(series.values()) / max(len(series), 1), 1),
                    }
            except Exception as e:
                errors.append(f"Batch {batch}: {str(e)}")

        ranked = sorted(
            (
                (b, r["avg_interest"])
                for b, r in per_brand_results.items()
                if isinstance(r, dict) and "avg_interest" in r
            ),
            key=lambda x: x[1],
            reverse=True,
        )

        result = {
            "brands": brands,
            "time_range": timeframe,
            "per_brand": per_brand_results,
            "relative_ranking_by_avg_interest": [b for b, _ in ranked],
            "source": "Google Trends (search interest proxy, not POS data)",
        }
        if len(batches) > 1:
            result["note"] = (
                f"More than {MAX_TERMS_PER_REQUEST} brands were requested; results were "
                f"fetched in batches with '{brands[0]}' as a common anchor. Cross-batch "
                f"comparisons are approximate."
            )
        if errors:
            result["errors"] = errors

        # Stash structured result so downstream tools (e.g. generate_dashboard)
        # can use real numbers without the LLM having to retype them.
        sly_data["last_sales_data"] = result

        return result

    @staticmethod
    def _normalize_brands(args: Dict[str, Any]) -> List[str]:
        brands = args.get("brands")
        if brands:
            return list(brands)
        scope = args.get("scope")
        return [scope] if scope else []

    @staticmethod
    def _batch_brands(brands: List[str]) -> List[List[str]]:
        if len(brands) <= MAX_TERMS_PER_REQUEST:
            return [brands]
        anchor = brands[0]
        rest = brands[1:]
        batches = []
        chunk_size = MAX_TERMS_PER_REQUEST - 1
        for i in range(0, len(rest), chunk_size):
            batches.append([anchor] + rest[i : i + chunk_size])
        return batches

    @staticmethod
    def _normalize_timeframe(time_range: str) -> str:
        mapping = {
            "last 3 months": "today 3-m",
            "last 6 months": "today 6-m",
            "last 12 months": "today 12-m",
            "last month": "today 1-m",
            "last week": "now 7-d",
        }
        return mapping.get(time_range.lower().strip(), time_range)

    @staticmethod
    def _trend_direction(values: list) -> str:
        if len(values) < 2:
            return "insufficient data"
        first_half_avg = sum(values[: len(values) // 2]) / max(len(values) // 2, 1)
        second_half_avg = sum(values[len(values) // 2 :]) / max(len(values) - len(values) // 2, 1)
        if second_half_avg > first_half_avg * 1.1:
            return "rising"
        if second_half_avg < first_half_avg * 0.9:
            return "declining"
        return "stable"

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method because it's quick, non-blocking.
        """
        return self.invoke(args, sly_data)    
