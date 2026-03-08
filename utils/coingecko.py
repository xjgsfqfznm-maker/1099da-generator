"""
Bitcoin Historical Price Fetcher (Kraken OHLC API)

Fetches the daily BTC/USD closing price for each unique transaction date.
Results are cached in-memory for the lifetime of the process to avoid
redundant API calls.

Uses the Kraken public OHLC endpoint — no API key required.

PRIVACY: Only dates (converted to Unix timestamps) are sent to Kraken — no
amounts, addresses, or transaction data leave the server.
"""
import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_PAIR = "XBTUSD"
INTERVAL_DAILY = 1440  # minutes

_price_cache: dict[str, float] = {}
_last_request_time: float = 0.0
_MIN_REQUEST_GAP = 1.5  # seconds between requests


def _throttle() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - elapsed)
    _last_request_time = time.monotonic()


def get_btc_price_on_date(iso_date: str) -> Optional[float]:
    """
    Return the BTC/USD closing price for a given ISO date string (YYYY-MM-DD).
    Uses in-memory cache; fetches from Kraken OHLC on cache miss.
    Returns None if the request fails.
    """
    if iso_date in _price_cache:
        return _price_cache[iso_date]

    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        logger.warning(f"Invalid date for price lookup: {iso_date}")
        return None

    # Convert date to Unix timestamp (start of day UTC)
    since_ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())

    _throttle()

    try:
        resp = requests.get(
            KRAKEN_OHLC_URL,
            params={
                "pair": KRAKEN_PAIR,
                "interval": INTERVAL_DAILY,
                "since": since_ts,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            logger.warning(f"Kraken API error for {iso_date}: {data['error']}")
            return None

        result = data.get("result", {})
        candles = result.get("XXBTZUSD") or result.get("XBTUSD") or []
        if not candles:
            logger.warning(f"Kraken: no candle data returned for {iso_date}")
            return None

        # Candle format: [time, open, high, low, close, vwap, volume, count]
        close_price = round(float(candles[0][4]), 2)
        _price_cache[iso_date] = close_price
        logger.info(f"Kraken: BTC on {iso_date} = ${close_price:,.2f}")
        return close_price

    except (requests.RequestException, KeyError, ValueError, TypeError, IndexError) as e:
        logger.warning(f"Kraken price fetch failed for {iso_date}: {e}")
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
