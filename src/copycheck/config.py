import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_dotenv(path=ENV_FILE):
    """Läser .env i repots rot. Riktiga miljövariabler vinner."""
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()

KALSHI_BASE_URL = os.environ.get("KALSHI_BASE_URL", "https://external-api.kalshi.com/trade-api/v2")
# Reserv: gav fel på /markets i testet 2026-11-10.
KALSHI_FALLBACK_URL = os.environ.get(
    "KALSHI_FALLBACK_URL", "https://api.elections.kalshi.com/trade-api/v2"
)
POLYMARKET_DATA_URL = os.environ.get("POLYMARKET_DATA_URL", "https://data-api.polymarket.com")
POLYMARKET_GAMMA_URL = os.environ.get("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
# AI för matchningen (fas 3). Alla har OpenAI-kompatibla API:er.
# leverantör: (bas-URL, miljövariabel med nyckeln, standardmodell)
LLM_PROVIDERS = {
    "anthropic": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY", "claude-sonnet-5-5"),
    "opper": ("https://api.opper.ai/v3/compat", "OPPER_API_KEY", "anthropic/claude-sonnet-5-5"),
    "berget": ("https://api.berget.ai/v1", "BERGET_API_KEY", "moonshotai/Kimi-K3.1-Pro"),
}
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
# USD per miljon tokens (in, ut). Källa: platform.claude.com, 2026-11-11.
LLM_PRICES = {
    "anthropic:claude-sonnet-5-5": (2.0, 10.0),
    "opper:anthropic/claude-sonnet-5-5": (2.0, 10.0),
}
LLM_PRICE_UNKNOWN = (10.0, 50.0)  # högt med flit, så att gränsen hellre slår till för tidigt
# Kostnadsgräns för all AI-matchning, summerad över alla körningar.
# 50 USD är ca 46 EUR, under Robins gräns på 50 EUR.
MAX_LLM_USD = float(os.environ.get("MAX_LLM_USD", "50"))

DB_PATH = os.environ.get("COPYCHECK_DB", "copycheck.db")
TRAIN_DAYS = 90
TEST_DAYS = 60
MIN_SIGNAL_USD = 250
SIGNAL_WINDOW = 10 * 60
TOP_TRADERS = 10  # match, backtest och live använder samma antal (Robin 2026-11-11)
