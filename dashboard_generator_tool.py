"""
dashboard_generator_tool.py

Generates a portfolio market-intelligence dashboard image (PNG) from the
REAL structured data produced earlier in the run by:
    - sales_data_tool.py       -> sly_data["last_sales_data"]
    - feedback_data_tool.py    -> sly_data["last_share_of_voice"]
    - sentiment_tool.py        -> sly_data["last_sentiment_by_brand"]
    - competitor_data_tool.py  -> sly_data["last_press_activity"]

Reading from sly_data (rather than having the LLM re-type large JSON blobs
between agent turns) avoids transcription errors and keeps numeric data
grounded in what the tools actually returned.

This tool should be called LAST, after market_trend_analyst,
customer_feedback_analyst, and competitive_intel_agent have all run in the
current conversation turn (a multi-brand request).

Setup:
    pip install matplotlib numpy
Output:
    Renders the PNG entirely IN MEMORY (no file written to disk) and returns
    it as a base64 data URI (`image_data_uri`). The calling agent embeds this
    directly in its chat response as a markdown image:
        ![CPG Portfolio Dashboard](<image_data_uri>)
    Most Neuro SAN chat clients (nsflow, the web client, Slack app) render
    markdown images given as data URIs inline, so the picture shows up
    directly in the conversation rather than as a file path the user has to
    go open separately.

    Note on size: data URIs count against the conversation's token budget
    (base64 adds ~33% overhead on top of the PNG's byte size), so this tool
    keeps the figure at a modest DPI/size to stay well within a typical
    context window. If your chat client does NOT render inline images from
    data URIs, switch back to saving a file and returning its path instead --
    see the commented-out disk-based version at the bottom of _render.
"""

import base64
import io
import os, time
import logging
from typing import Any, Dict, List,Union
import matplotlib
matplotlib.use("Agg")  # headless rendering, no display needed
import matplotlib.pyplot as plt
import numpy as np
from neuro_san.interfaces.coded_tool import CodedTool

logger = logging.getLogger(__name__)

PALETTE = ["#2E86AB", "#E67E22", "#27AE60", "#060506", "#C0392B", "#16A085"]


class DashboardGeneratorTool(CodedTool):
    """
    CodedTool that renders a multi-panel dashboard from real per-brand
    data gathered by the other tools in this network, via sly_data.
    """

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        brands: List[str] = args.get("brands") or self._infer_brands(sly_data)

        if not brands:
            return {
                "error": "No brands found. Either pass 'brands' explicitly or ensure "
                "market_trend_analyst / customer_feedback_analyst / "
                "competitive_intel_agent ran earlier in this conversation."
            }

        sales_data = sly_data.get("last_sales_data", {}).get("per_brand", {})
        share_of_voice = sly_data.get("last_share_of_voice", {})
        sentiment_by_brand = sly_data.get("last_sentiment_by_brand", {})
        press_activity = sly_data.get("last_press_activity", {})

        missing = []
        if not sales_data:
            missing.append("market trend data")
        if not share_of_voice:
            missing.append("share of voice data")
        if not sentiment_by_brand:
            missing.append("sentiment data")
        if not press_activity:
            missing.append("press activity data")

        try:
            image_data_uri = self._render(
                brands, sales_data, share_of_voice, sentiment_by_brand, press_activity
            )
        except Exception as e:
            return {"error": f"Failed to render dashboard: {str(e)}"}

        description = self._build_description(
            brands, sales_data, share_of_voice, sentiment_by_brand, press_activity
        )

        result = {
            "image_data_uri": image_data_uri,
            "description": description,
            "brands_included": brands,
            "panels": [
                "search interest trend",
                "share of voice",
                "sentiment split",
                "avg search interest ranking",
                "press/news activity",
            ],
        }
        if missing:
            result["note"] = (
                f"Some data was unavailable and those panels may be incomplete: "
                f"{', '.join(missing)}."
            )
        return result

    # -----------------------------------------------------------------
    @staticmethod
    def _build_description(
        brands: List[str],
        sales_data: Dict[str, Any],
        share_of_voice: Dict[str, float],
        sentiment_by_brand: Dict[str, Any],
        press_activity: Dict[str, int],
    ) -> str:
        """
        Builds a plain-language description of the dashboard DIRECTLY from
        the same numbers used to render it, so the text stays grounded in
        actual data rather than being separately guessed by an LLM.
        """
        lines = []

        # Trend leader / laggard
        avg_interest = {b: (sales_data.get(b) or {}).get("avg_interest") for b in brands}
        avg_interest = {b: v for b, v in avg_interest.items() if v is not None}
        if avg_interest:
            leader = max(avg_interest, key=avg_interest.get)
            laggard = min(avg_interest, key=avg_interest.get)
            leader_dir = (sales_data.get(leader) or {}).get("trend_direction", "unknown")
            lines.append(
                f"{leader} has the highest average search interest ({avg_interest[leader]:.0f}/100, "
                f"trend: {leader_dir})."
            )
            if laggard != leader:
                laggard_dir = (sales_data.get(laggard) or {}).get("trend_direction", "unknown")
                lines.append(
                    f"{laggard} has the lowest average search interest ({avg_interest[laggard]:.0f}/100, "
                    f"trend: {laggard_dir})."
                )

        # Share of voice leader
        if share_of_voice:
            sov_leader = max(share_of_voice, key=share_of_voice.get)
            lines.append(
                f"{sov_leader} accounts for the largest share of social discussion volume "
                f"({share_of_voice[sov_leader] * 100:.0f}% of tracked mentions)."
            )

        # Sentiment leader / laggard
        pos_scores = {
            b: (sentiment_by_brand.get(b) or {}).get("proportions", {}).get("positive")
            for b in brands
        }
        pos_scores = {b: v for b, v in pos_scores.items() if v is not None}
        if pos_scores:
            best_sentiment = max(pos_scores, key=pos_scores.get)
            worst_sentiment = min(pos_scores, key=pos_scores.get)
            lines.append(
                f"{best_sentiment} has the most positive customer sentiment "
                f"({pos_scores[best_sentiment] * 100:.0f}% positive feedback)."
            )
            if worst_sentiment != best_sentiment:
                lines.append(
                    f"{worst_sentiment} has the least positive sentiment "
                    f"({pos_scores[worst_sentiment] * 100:.0f}% positive feedback) and may "
                    f"warrant attention."
                )

        # Press activity leader
        if press_activity:
            press_leader = max(press_activity, key=press_activity.get)
            if press_activity[press_leader] > 0:
                lines.append(
                    f"{press_leader} shows the most recent press/news activity "
                    f"({press_activity[press_leader]} articles), suggesting active "
                    f"marketing or competitive moves."
                )

        if not lines:
            return (
                "Not enough data was available to generate a grounded description. "
                "Check that market, feedback, and competitive data were gathered "
                "before calling generate_dashboard."
            )

        return " ".join(lines)

    # -----------------------------------------------------------------
    @staticmethod
    def _infer_brands(sly_data: Dict[str, Any]) -> List[str]:
        for key in (
            "last_sales_data",
            "last_share_of_voice",
            "last_sentiment_by_brand",
            "last_press_activity",
        ):
            val = sly_data.get(key)
            if isinstance(val, dict):
                per_brand = val.get("per_brand", val)
                if isinstance(per_brand, dict) and per_brand:
                    return list(per_brand.keys())
        return []

    def _render(
        self,
        brands: List[str],
        sales_data: Dict[str, Any],
        share_of_voice: Dict[str, float],
        sentiment_by_brand: Dict[str, Any],
        press_activity: Dict[str, int],
    ) -> str:
        """Returns a base64 PNG data URI (e.g. 'data:image/png;base64,...')."""
        colors = [PALETTE[i % len(PALETTE)] for i in range(len(brands))]

        # Kept deliberately compact: this image is embedded as a base64 data
        # URI directly in the chat response, so every extra pixel costs
        # conversation tokens (base64 adds ~33% on top of PNG byte size).
        fig = plt.figure(figsize=(10, 7), facecolor="white")
        fig.suptitle(
            "CPG Portfolio Market Intelligence Dashboard",
            fontsize=18, fontweight="bold", y=0.98,
        )
        gs = fig.add_gridspec(3, 2, hspace=0.45, wspace=0.3, top=0.92, bottom=0.06, left=0.08, right=0.95)

        # 1. Search interest trend
        ax1 = fig.add_subplot(gs[0, :])
        any_trend = False
        for i, brand in enumerate(brands):
            series = (sales_data.get(brand) or {}).get("interest_over_time")
            if not series:
                continue
            any_trend = True
            dates = list(series.keys())
            values = list(series.values())
            ax1.plot(dates, values, marker="o", linewidth=2, color=colors[i], label=brand)
        ax1.set_title("Search Interest Trend (Google Trends proxy)", fontsize=13, fontweight="bold", loc="left")
        ax1.set_ylabel("Relative interest (0-100)")
        if any_trend:
            ax1.legend(loc="upper left", ncol=min(len(brands), 4), frameon=False, fontsize=9)
            ax1.tick_params(axis="x", rotation=45, labelsize=7)
        else:
            ax1.text(0.5, 0.5, "No trend data available", ha="center", va="center", transform=ax1.transAxes)
        ax1.spines[["top", "right"]].set_visible(False)
        ax1.grid(axis="y", alpha=0.3)

        # 2. Share of voice
        ax2 = fig.add_subplot(gs[1, 0])
        sov_values = [share_of_voice.get(b, 0) for b in brands]
        if sum(sov_values) > 0:
            ax2.pie(
                sov_values, labels=brands, colors=colors, autopct="%1.0f%%",
                startangle=90, wedgeprops=dict(width=0.4), pctdistance=0.8,
                textprops={"fontsize": 9},
            )
        else:
            ax2.text(0.5, 0.5, "No share-of-voice data", ha="center", va="center", transform=ax2.transAxes)
            ax2.axis("off")
        ax2.set_title("Share of Voice (social volume)", fontsize=13, fontweight="bold")

        # 3. Sentiment split
        ax3 = fig.add_subplot(gs[1, 1])
        pos = [sentiment_by_brand.get(b, {}).get("proportions", {}).get("positive", 0) * 100 for b in brands]
        neu = [sentiment_by_brand.get(b, {}).get("proportions", {}).get("neutral", 0) * 100 for b in brands]
        neg = [sentiment_by_brand.get(b, {}).get("proportions", {}).get("negative", 0) * 100 for b in brands]
        y_pos = np.arange(len(brands))
        if any(pos) or any(neu) or any(neg):
            ax3.barh(y_pos, pos, color="#27AE60", label="Positive")
            ax3.barh(y_pos, neu, left=pos, color="#BDC3C7", label="Neutral")
            ax3.barh(y_pos, neg, left=np.array(pos) + np.array(neu), color="#E74C3C", label="Negative")
            ax3.legend(loc="lower right", frameon=False, fontsize=8, ncol=3)
        else:
            ax3.text(0.5, 0.5, "No sentiment data", ha="center", va="center", transform=ax3.transAxes)
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(brands, fontsize=9)
        ax3.set_xlabel("% of feedback")
        ax3.set_title("Customer Sentiment Split", fontsize=13, fontweight="bold", loc="left")
        ax3.spines[["top", "right"]].set_visible(False)
        ax3.invert_yaxis()

        # 4. Avg interest ranking
        ax4 = fig.add_subplot(gs[2, 0])
        avg_interest = [(sales_data.get(b) or {}).get("avg_interest", 0) for b in brands]
        if any(avg_interest):
            order = np.argsort(avg_interest)[::-1]
            ax4.bar([brands[i] for i in order], [avg_interest[i] for i in order],
                    color=[colors[i] for i in order])
            ax4.tick_params(axis="x", rotation=30, labelsize=8)
        else:
            ax4.text(0.5, 0.5, "No interest data", ha="center", va="center", transform=ax4.transAxes)
        ax4.set_title("Avg. Search Interest (ranked)", fontsize=13, fontweight="bold", loc="left")
        ax4.set_ylabel("Avg interest (0-100)")
        ax4.spines[["top", "right"]].set_visible(False)
        ax4.grid(axis="y", alpha=0.3)

        # 5. Press activity
        ax5 = fig.add_subplot(gs[2, 1])
        press_values = [press_activity.get(b, 0) for b in brands]
        if any(press_values):
            order2 = np.argsort(press_values)[::-1]
            ax5.bar([brands[i] for i in order2], [press_values[i] for i in order2],
                    color=[colors[i] for i in order2])
            ax5.tick_params(axis="x", rotation=30, labelsize=8)
        else:
            ax5.text(0.5, 0.5, "No press activity data", ha="center", va="center", transform=ax5.transAxes)
        ax5.set_title("Press/News Activity (article count)", fontsize=13, fontweight="bold", loc="left")
        ax5.set_ylabel("Article count")
        ax5.spines[["top", "right"]].set_visible(False)
        ax5.grid(axis="y", alpha=0.3)

        # Render to an in-memory buffer instead of a file on disk, so the
        # image can be embedded directly in the chat response.
        buffer = io.BytesIO()
        plt.savefig(buffer, format="png", dpi=85, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode("utf-8")
        buffer.close()

        return f"data:image/png;base64,{encoded}"

        # --- Disk-based alternative (use if your chat client can't render
        # data URIs inline) ---
        # import os, time
        #OUTPUT_DIR = os.environ.get("DASHBOARD_OUTPUT_DIR", "/mnt/user-data/outputs")
        #os.makedirs(OUTPUT_DIR, exist_ok=True)
        #filename = f"cpg_portfolio_dashboard_{int(time.time())}.png"
        #path = os.path.join(OUTPUT_DIR, filename)
        #plt.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        #plt.close(fig)
       # return path

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method because it's quick, non-blocking.
        """
        return self.invoke(args, sly_data)      