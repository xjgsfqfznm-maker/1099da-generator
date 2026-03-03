"""
CoinGecko Historical Bitcoin Price Fetcher

Fetches the daily BTC/USD closing price for each unique transaction date.
Results are cached in-memory for the lifetime of the process to avoid
redundant API calls (CoinGecko free tier: 30 calls/minute).

PRIVACY: Only dates are sent to CoinGecko — no amounts, addresses, or
transaction data leave the server.
"""
import logging
import time
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/history"

_price_cache: dict[str, float] = {}
_last_request_time: float = 0.0
_MIN_REQUEST_GAP = 2.1  # seconds between requests (free tier: ~30/min)


def _throttle() -> None:
    """Ensure we don't exceed CoinGecko free-tier rate limits."""
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - elapsed)
    _last_request_time = time.monotonic()


def get_btc_price_on_date(iso_date: str) -> Optional[float]:
    """
    Return the BTC/USD price for a given ISO date string (YYYY-MM-DD).
    Uses in-memory cache; fetches from CoinGecko on cache miss.
    Returns None if the request fails.
    """
    if iso_date in _price_cache:
        return _price_cache[iso_date]

    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        logger.warning(f"Invalid date for price lookup: {iso_date}")
        return None

    # CoinGecko expects DD-MM-YYYY
    cg_date = d.strftime("%d-%m-%Y")

    _throttle()

    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"date": cg_date, "localization": "false"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        price = data["market_data"]["current_price"]["usd"]
        price = round(float(price), 2)
        _price_cache[iso_date] = price
        logger.info(f"CoinGecko: BTC on {iso_date} = ${price:,.2f}")
        return price
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        logger.warning(f"CoinGecko price fetch failed for {iso_date}: {e}")
        return None


def enrich_transactions_with_prices(
    transactions: list[dict],
) -> tuple[list[dict], dict[str, float]]:
    """
    Fetch a BTC/USD price for every unique transaction date and attach it
    to each transaction as 'market_price_usd'.

    Returns:
        (enriched_transactions, price_map)
        price_map maps ISO date -> USD price (or None if unavailable)
    """
    unique_dates = sorted({tx["date"] for tx in transactions if tx.get("date")})
    price_map: dict[str, Optional[float]] = {}

    for d in unique_dates:
        price_map[d] = get_btc_price_on_date(d)

    enriched = []
    for tx in transactions:
        tx_copy = dict(tx)
        tx_copy["market_price_usd"] = price_map.get(tx.get("date", ""))
        enriched.append(tx_copy)

    return enriched, {k: v for k, v in price_map.items() if v is not None}
