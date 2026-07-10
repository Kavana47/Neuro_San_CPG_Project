CPG Market Intelligence — Neuro SAN Agent Network

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

.
├── coded_tools/
│   └── basic/
│     └── cpg_Maket_Intelli/
│         ├── brand_discovery_tool.py     # Finds top brands for a product/country (Google Trends)
│         ├── sales_data_tool.py          # Search/sales interest trends (Google Trends)
│         ├── feedback_data_tool.py       # Customer feedback snippets (DuckDuckGo search)
│         ├── sentiment_tool.py           # Offline sentiment scoring (VADER)
│         └── competitor_data_tool.py     # Competitor news/launches (NewsAPI.org)
├── registries/
│   └── basic/
│     ├── cpg_Market_Intelli/
│     │     └── cpg_market_intelligence.hocon   # The agent network definition
│     └── manifest.hocon                      # Registers the network with the server
├── docs/
│   ├── architecture.md
│   └── summary.md
├── .env
├── requirements.txt
└── README.md


Prerequisites


1. Python 3.10+
2. A working neuro-san-studio installation (this project's coded_tools/ and registries/ are designed to be dropped into a neuro-san-studio checkout, or run against the neuro-san-studio PyPI package — see its README for setup)
3. An MistralAI (or other supported LLM provider) API key
4. A free NewsAPI.org API key (competitive intelligence agent)

Setup

1. Clone the repo:

git clone https://github.com/cognizant-ai-lab/neuro-san-studio

2. Go to dir:

cd neuro-san-studio

3. Ensure you have a supported version of python (e.g. 3.12 or 3.13):

python --version

4. (Important) Point neuro-san-studio at this project's registry and coded tools.
Merge (or symlink) this repo's registries/ and coded_tools/ into your neuro-san-studio.

5. Create a dedicated Python virtual environment:

python -m venv venv

6. Source it:

For Windows:

.\venv\Scripts\activate.bat

source venv/bin/activate

7. Install the requirements:

pip install -r requirements.txt

IMPORTANT: By default, the server relies on OpenAI's gpt-5.2 model. But in this project we have used Mistral AI. You can get your OpenAI API key from https://admin.mistral.ai/organization/api-keys

You can set the key in .env file MISTRAL_API_KEY="XXX"
NOTE: Replace XXX with your actual OpenAI API key.

Run

Neuro SAN Studio provides a user-friendly environment to interact with agent networks.

1. Start the server and client with a single command, from the project root directory:

python -m neuro_san_studio run

2. Navigate to http://localhost:4173/ to access the UI.

