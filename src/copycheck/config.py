import os

KALSHI_BASE_URL = os.environ.get("KALSHI_BASE_URL", "https://external-api.kalshi.com/trade-api/v2")
# Reserv: gav fel på /markets i testet 2026-11-10.
KALSHI_FALLBACK_URL = os.environ.get(
    "KALSHI_FALLBACK_URL", "https://api.elections.kalshi.com/trade-api/v2"
)
POLYMARKET_DATA_URL = os.environ.get("POLYMARKET_DATA_URL", "https://data-api.polymarket.com")

DB_PATH = os.environ.get("COPYCHECK_DB", "copycheck.db")
TRAIN_DAYS = 90
TEST_DAYS = 60
