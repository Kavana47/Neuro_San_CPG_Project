@@ -1 +1,111 @@
# Consumer Packaged Goods(CPG) Market Intelligence using Neuro SAN Agent Network

A multi-agent system built on Cognizant's Neuro SAN that analyzes market trends, customer feedback, and competitive activity for consumer packaged goods (CPG) products, and compiles the findings into a structured summary report.

Given a product/category (e.g. "Soaps") and, optionally, a country and a list of brands, the network:

1.Discovers the top brands in that market (if not supplied)
2.Analyzes search/sales interest trends per brand
3.Analyzes customer feedback sentiment per brand
4.Tracks competitor news/promotional activity per brand
5.Compares brands against each other (if more than one brand is in scope)
6.Compiles everything into a final structured summary, delivered in chat

Project Structure

Following the standard neuro-san-studio project layout:

```
.
├── coded_tools/
│   └── basic/
│     └── cpg_Maket_Intelli/
│         ├── brand_discovery_tool.py     # Finds top brands for a product/country (Google Trends)
│         ├── sales_data_tool.py          # Search/sales interest trends (Google Trends)
│         ├── feedback_data_tool.py       # Customer feedback snippets (DuckDuckGo search)
│         ├── sentiment_tool.py           # Offline sentiment scoring (VADER)
│         └── competitor_data_tool.py     # Competitor news/launches (NewsAP├── frontend/
├── registries/
│   └── basic/
│     ├── cpg_Market_Intelli/
│     │     └── cpg_market_intelligence.hocon   # The agent network definition
│     └── manifest.hocon                      # Registers the network with the server
├── frontend/
│   ├── streamlit_app.py                # Streamlit UI, talks to the server over HTTP
│   ├── requirements.txt
├── architecture.md
├── summary.md
├── .env
├── requirements.txt
└── README.md
```

## Prerequisites

1. Python 3.10+
2. A working neuro-san-studio installation (this project's coded_tools/ and registries/ are designed to be dropped into a neuro-san-studio checkout, or run against the neuro-san-studio. 
3. An MistralAI (or other supported LLM provider) API key
4. A free NewsAPI.org API key (competitive intelligence agent)

## Setup

1. **Clone this repo alongside (or on top of) a neuro-san-studio checkout:https://github.com/cognizant-ai-lab/neuro-san-studio **

   ```bash
   git clone https://github.com/Kavana47/Neuro_San_CPG_Project cpg-market-intelligence
   cd cpg-market-intelligence
   ```

2. **Create a virtual environment and install dependencies:**

   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   # Also install neuro-san-studio's own requirements if not already installed
   ```

3. **Configure environment variables:**

   ```bash
   cp .env.example .env
   # then edit .env and fill in MISTRAL_API_KEY and NEWSAPI_KEY
   ```

4. **Point neuro-san-studio at this project's registry and coded tools.**
   Merge (or symlink) this repo's `registries/` and `coded_tools/` into your neuro-san-studio checkout, or set:

   
5. **Run the server:**

   ```bash
   python -m run
    ```
 Then open the `nsflow` UI (or your preferred Neuro SAN client) and select the `CPG_Market_Intelligence` network.

6. **Run the Streamlit frontend**  alongside `nsflow`:

   ```bashhttps://github.com/Kavana47/Neuro_San_CPG_Projec
   cd frontend
   streamlit run streamlit_app.py
   ```

## Example Usage

```
Analyze the milk market in India — compare the top 5 brands on trends, feedback, and competitive activity.
```

The orchestrator will:
- Confirm the product ("Soaps") and default the country to India if not stated
- Call `brand_discovery_agent` to surface candidate top brands (flagged as a search-interest-based proxy, not a certified market-share ranking)
- Run trend, feedback, and competitive analysis for each brand
- Run a cross-brand portfolio comparison
- Return a structured summary in chat

## Known Limitations

- **Brand discovery and trend rankings are search-interest proxies** (Google Trends), not certified retail sales/market-share data. For certified numbers, integrate a syndicated data provider (Nielsen IQ, Kantar Worldpanel, Circana/IRI) in place of `sales_data_tool.py` / `brand_discovery_tool.py`.
- **Feedback data comes from DuckDuckGo search snippets** (reviews/complaints found via web search), not a curated review database. It's a free, no-API-key source, but treat sentiment as directional rather than definitive. Swap `feedback_data_tool.py` for a review-platform integration (Bazaarvoice, Yotpo, etc.) for production use.
- **Competitive intelligence depends on NewsAPI.org's free tier** (500 requests/day), which is sufficient for prototyping but may need a paid tier for heavier use.
