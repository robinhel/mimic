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
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

DB_PATH = os.environ.get("COPYCHECK_DB", "copycheck.db")
TRAIN_DAYS = 90
TEST_DAYS = 60
MIN_SIGNAL_USD = 250
SIGNAL_WINDOW = 10 * 60
