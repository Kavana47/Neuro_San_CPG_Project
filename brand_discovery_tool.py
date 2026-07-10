"""
brand_discovery_tool.py

Given a product or category (e.g. "oat milk", "laundry detergent"), returns
a candidate list of brands active in that space, scoped to a specific
country (default: India), and ranks them by relative search-interest
volume in that country as a proxy for market presence -- returning the
top N (default 5).

IMPORTANT LIMITATIONS:
- Candidate discovery uses Google Trends related queries, which is a
  HEURISTIC signal, not an authoritative brand registry. It can surface
  retailer names, generic terms, or miss smaller/regional brands entirely.
- The "top N" ranking is based on RELATIVE SEARCH INTEREST in the given
  country, which is a proxy for consumer attention/market presence -- it is
  NOT verified retail sales market share. Two brands can have very different
  actual revenue/shelf share while having similar search interest (e.g. a
  cheap high-volume brand vs. a premium low-volume one).
- For a certified, sales-based market-share ranking, use a syndicated data
  provider with India coverage: Nielsen IQ India, Kantar Worldpanel India,
  or Euromonitor. Swap _rank_by_interest for a call to that provider's API
  and the rest of the pipeline (CodedTool interface) stays the same.
- Always present results to the user as a starting point to confirm/edit,
  not a final answer.

Setup:
    pip install pytrends
No API key required.
"""

import re
from typing import Any, Dict, List, Union
from pytrends.request import TrendReq
from neuro_san.interfaces.coded_tool import CodedTool

MAX_TERMS_PER_REQUEST = 5  # Google Trends comparison cap

# Generic words that show up in related-queries results but aren't brand
# names -- filtered out to reduce noise in the candidate list.
GENERIC_TERMS = {
    "best", "near me", "reviews", "review", "price", "prices", "cheap",
    "walmart", "amazon", "target", "costco", "kroger", "buy", "online",
    "vs", "recipe", "recipes", "brands", "brand", "healthy", "organic",
    "sale", "coupon", "coupons", "deals", "how to", "what is",
    "flipkart", "bigbasket", "blinkit", "zepto", "amazon in", "amazon india",
}

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


class BrandDiscoveryTool(CodedTool):
    """
    CodedTool that returns the top-N brands (by relative search interest,
    as a market-presence proxy) for a given product/category within a
    given country. Defaults to India.
    """

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        product = args.get("product")
        country = args.get("country", DEFAULT_COUNTRY)
        max_brands = int(args.get("max_brands", 5))

        if not product:
            return {"error": "Missing required 'product' argument (product or category name)."}

        geo = self._resolve_geo(country)

        try:
            candidates = self._fetch_candidates(product, geo)
        except Exception as e:
            return {
                "error": f"Failed to fetch brand candidates: {str(e)}",
                "product": product,
                "country": country,
                "fallback_note": (
                    "Data lookup failed. Fall back to well-known brands you're "
                    "confident are sold in this country for this category, and "
                    "clearly label them as an unverified, AI-generated candidate list."
                ),
            }

        if not candidates:
            return {
                "product": product,
                "country": country,
                "candidate_brands": [],
                "note": f"No candidate brands found via search-query patterns for '{product}' in {country}.",
            }

        try:
            ranked = self._rank_by_interest(candidates, geo)
        except Exception as e:
            # Ranking failed but we still have an unranked candidate list --
            # return it rather than failing the whole call.
            ranked = None
            ranking_error = str(e)
        else:
            ranking_error = None

        top_brands = (ranked or candidates)[:max_brands]

        result = {
            "product": product,
            "country": country,
            "top_brands": top_brands,
            "all_candidates_considered": candidates,
            "ranking_basis": (
                "Relative Google Trends search interest within the specified country "
                "(a market-PRESENCE proxy, not verified retail sales market share)."
                if ranked
                else "Not ranked (see ranking_error) -- order reflects raw candidate discovery only."
            ),
            "source": "Google Trends related queries + comparative interest (heuristic, not authoritative)",
            "caveat": (
                "This is a candidate/ranking list based on search-interest patterns, not a "
                "verified brand database or certified market-share report. Confirm/edit "
                "before treating it as final. For certified market share in India, use a "
                "syndicated data provider such as Nielsen IQ India or Kantar Worldpanel."
            ),
        }
        if ranking_error:
            result["ranking_error"] = ranking_error

        sly_data["last_brand_candidates"] = result
        return result

    # -----------------------------------------------------------------
    @staticmethod
    def _resolve_geo(country: str) -> str:
        return COUNTRY_GEO_CODES.get(country.strip().lower(), "")

    @staticmethod
    def _fetch_candidates(product: str, geo: str) -> List[str]:
        pytrends = TrendReq(hl="en-US", tz=330 if geo == "IN" else 360)
        pytrends.build_payload([f"{product} brands"], timeframe="today 12-m", geo=geo)
        related = pytrends.related_queries()

        query_key = f"{product} brands"
        data = related.get(query_key, {})
        top_df = data.get("top")
        rising_df = data.get("rising")

        raw_terms: List[str] = []
        for df in (top_df, rising_df):
            if df is not None and not df.empty and "query" in df.columns:
                raw_terms.extend(df["query"].tolist())

        candidates = []
        seen = set()
        for term in raw_terms:
            cleaned = BrandDiscoveryTool._extract_brand_like(term, product)
            if cleaned and cleaned.lower() not in seen and cleaned.lower() not in GENERIC_TERMS:
                seen.add(cleaned.lower())
                candidates.append(cleaned)

        return candidates

    @staticmethod
    def _extract_brand_like(term: str, product: str) -> str:
        cleaned = term.lower()
        cleaned = cleaned.replace(product.lower(), "")
        cleaned = re.sub(r"\bbrands?\b", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned or cleaned in GENERIC_TERMS or len(cleaned) < 2:
            return ""
        return cleaned.title()

    @staticmethod
    def _rank_by_interest(candidates: List[str], geo: str) -> List[str]:
        """
        Ranks candidate brands by average relative search interest within
        `geo`, batching in groups of 5 (Google Trends' comparison cap) with
        the first candidate repeated as a common anchor across batches so
        scores stay roughly comparable when there are more than 5 candidates.
        """
        pytrends = TrendReq(hl="en-US", tz=330 if geo == "IN" else 360)

        if len(candidates) <= MAX_TERMS_PER_REQUEST:
            batches = [candidates]
        else:
            anchor = candidates[0]
            rest = candidates[1:]
            chunk_size = MAX_TERMS_PER_REQUEST - 1
            batches = [
                [anchor] + rest[i : i + chunk_size] for i in range(0, len(rest), chunk_size)
            ]

        avg_interest: Dict[str, float] = {}
        for batch in batches:
            pytrends.build_payload(batch, timeframe="today 12-m", geo=geo)
            interest_over_time = pytrends.interest_over_time()
            if interest_over_time.empty:
                continue
            for brand in batch:
                if brand in interest_over_time.columns:
                    avg_interest[brand] = round(interest_over_time[brand].mean(), 1)

        if not avg_interest:
            raise RuntimeError("Google Trends returned no interest data to rank candidates by.")

        # Any candidate that never got a score (e.g. a batch failed) goes to
        # the bottom rather than being silently dropped.
        ranked = sorted(candidates, key=lambda b: avg_interest.get(b, -1), reverse=True)
        return ranked
    
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method because it's quick, non-blocking.
        """
        return self.invoke(args, sly_data)