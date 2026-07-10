"""
sentiment_tool.py (multi-brand)

Scores sentiment for feedback text grouped by brand using VADER (tuned for
short, informal text -- reviews, social posts, comments). Runs fully
offline, no API key required. Returns per-brand proportions plus a ranking
so brands can be compared directly.

Setup:
    pip install vaderSentiment
"""

from typing import Any, Dict, List,Union
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from neuro_san.interfaces.coded_tool import CodedTool


class SentimentTool(CodedTool):
    """
    CodedTool that scores sentiment per brand and returns proportions plus
    a ranking from most to least positive.
    """

    def __init__(self):
        self._analyzer = SentimentIntensityAnalyzer()

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        texts_by_brand: Dict[str, List[str]] = (
            args.get("texts_by_brand") or sly_data.get("last_feedback_texts_by_brand", {})
        )

        if not texts_by_brand:
            return {
                "error": "No texts_by_brand provided and none found in "
                "sly_data['last_feedback_texts_by_brand']."
            }

        per_brand_results: Dict[str, Any] = {}

        for brand, texts in texts_by_brand.items():
            if not texts:
                per_brand_results[brand] = {"note": "No feedback text available for this brand."}
                continue

            pos = neu = neg = 0
            compound_scores = []

            for text in texts:
                polarity = self._analyzer.polarity_scores(text)
                compound_scores.append(polarity["compound"])
                label = self._label(polarity["compound"])
                if label == "positive":
                    pos += 1
                elif label == "negative":
                    neg += 1
                else:
                    neu += 1

            total = len(texts)
            avg_compound = round(sum(compound_scores) / total, 3)

            per_brand_results[brand] = {
                "count": total,
                "proportions": {
                    "positive": round(pos / total, 3),
                    "neutral": round(neu / total, 3),
                    "negative": round(neg / total, 3),
                },
                "avg_compound_score": avg_compound,
            }

        ranked = sorted(
            (
                (b, r["avg_compound_score"])
                for b, r in per_brand_results.items()
                if isinstance(r, dict) and "avg_compound_score" in r
            ),
            key=lambda x: x[1],
            reverse=True,
        )

        # Stash structured result so generate_dashboard can use real numbers.
        sly_data["last_sentiment_by_brand"] = per_brand_results

        return {
            "per_brand": per_brand_results,
            "sentiment_ranking_most_to_least_positive": [b for b, _ in ranked],
        }

    @staticmethod
    def _label(compound: float) -> str:
        if compound >= 0.05:
            return "positive"
        if compound <= -0.05:
            return "negative"
        return "neutral"
    
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method because it's quick, non-blocking.
        """
        return self.invoke(args, sly_data)    