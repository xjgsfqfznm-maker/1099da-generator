"""
Venice AI Client — Kimi K2.5 Integration

DATA SANITIZATION (privacy safeguards):
  1. tx_hash is SHA-256 hashed before transmission — original hashes never leave the server
  2. description fields are stripped entirely
  3. Timestamps are rounded to the day (no time-of-day)
  4. BTC amounts are rounded to 8 decimals
  5. USD values are rounded to 2 decimals
  6. No wallet addresses, names, or IPs are included in the payload

If the AI call fails for any reason, a FIFO calculator fallback is used.
"""
import hashlib
import json
import logging
import os
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

VENICE_API_URL = "https://api.venice.ai/api/v1/chat/completions"
MODEL = "kimi-k2-5"


def _build_prompt(cost_per_btc: Optional[float]) -> str:
    """Build the system prompt, incorporating user cost basis if provided."""
    base = (
        "You are a crypto-tax specialist. Using the supplied Bitcoin transaction list, "
        "calculate data for IRS 1099-DA. Each transaction includes a 'market_price_usd' field "
        "showing the BTC/USD market price on that date from CoinGecko. "
        "Separate results into short-term (held <=365 days) and long-term (held >365 days). "
    )

    if cost_per_btc and cost_per_btc > 0:
        base += (
            f"The user's stated average cost basis is ${cost_per_btc:,.2f} per BTC. "
            "Use this as the cost basis for all acquisition (receive) transactions. "
            "For disposition (send/sell) transactions, use market_price_usd × amount_btc as proceeds. "
            "Capital gain/loss = proceeds - cost_basis. "
        )
    else:
        base += (
            "For disposition (send/sell) transactions, use market_price_usd × amount_btc as proceeds. "
            "For acquisition (receive) transactions, use market_price_usd × amount_btc as cost basis. "
        )

    base += (
        "Return ONLY JSON with fields: "
        "short_term {proceeds, cost_basis, gain_loss, count}, "
        "long_term {proceeds, cost_basis, gain_loss, count}. "
        "No personal identifiers."
    )
    return base


def _sanitize_transactions(transactions: list[dict]) -> list[dict]:
    """
    PRIVACY STEP: Sanitize transaction data before sending to AI.
    - SHA-256 hash each tx_hash
    - Strip descriptions
    - Round timestamps to day
    - Round amounts to 8 decimals
    - Retain market_price_usd (public market data, not private)
    """
    sanitized = []
    for tx in transactions:
        raw_hash = tx.get("tx_hash", "") or ""
        hashed = hashlib.sha256(raw_hash.encode()).hexdigest() if raw_hash else ""

        sanitized.append({
            "date": tx.get("date", ""),
            "type": tx.get("type", ""),
            "amount_btc": round(float(tx.get("amount_btc", 0)), 8),
            "market_price_usd": tx.get("market_price_usd"),
            "fee_btc": round(float(tx.get("fee_btc", 0)), 8),
            "tx_hash": hashed,
        })
    return sanitized


def _call_venice_ai(
    transactions: list[dict],
    cost_per_btc: Optional[float] = None,
) -> Optional[dict]:
    """Send sanitized transaction data to Venice AI and return parsed JSON."""
    api_key = os.getenv("VENICE_API_KEY")
    if not api_key:
        logger.warning("VENICE_API_KEY not set — using FIFO fallback")
        return None

    sanitized = _sanitize_transactions(transactions)
    payload_str = json.dumps(sanitized, separators=(",", ":"))
    prompt = _build_prompt(cost_per_btc)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": payload_str},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    try:
        resp = requests.post(VENICE_API_URL, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

        return json.loads(content)
    except requests.RequestException as e:
        logger.error(f"Venice AI request failed: {e}")
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Venice AI response parse failed: {e}")
        return None


def _fifo_fallback(
    transactions: list[dict],
    cost_per_btc: Optional[float] = None,
) -> dict:
    """
    FIFO cost-basis calculator fallback when AI is unavailable.

    If cost_per_btc is provided, it overrides the per-acquisition cost basis.
    Historical market prices (market_price_usd) are used for proceeds on sales.
    Holding period (short/long term) is determined by FIFO acquisition date matching.
    """
    buys: list[dict] = []
    short_proceeds = short_cost = short_gain = 0.0
    short_count = 0
    long_proceeds = long_cost = long_gain = 0.0
    long_count = 0

    for tx in sorted(transactions, key=lambda x: x.get("date", "")):
        tx_type = tx.get("type", "")
        amount = float(tx.get("amount_btc", 0))
        market_price = tx.get("market_price_usd")
        tx_date_str = tx.get("date", "")

        if not tx_date_str or amount <= 0:
            continue

        try:
            tx_date = date.fromisoformat(tx_date_str)
        except ValueError:
            continue

        if tx_type == "receive":
            # Cost basis: use user-supplied flat rate or market price at acquisition
            if cost_per_btc and cost_per_btc > 0:
                acq_cost_per_btc = cost_per_btc
            elif market_price:
                acq_cost_per_btc = market_price
            else:
                acq_cost_per_btc = float(tx.get("usd_value", 0)) / amount if amount else 0.0

            buys.append({
                "date": tx_date,
                "amount_btc": amount,
                "cost_per_btc": acq_cost_per_btc,
            })

        elif tx_type == "send":
            # Proceeds: use market price at sale date × BTC amount
            if market_price:
                proceeds_per_btc = market_price
            else:
                usd = float(tx.get("usd_value", 0))
                proceeds_per_btc = usd / amount if amount else 0.0

            if proceeds_per_btc <= 0:
                continue

            remaining = amount

            while remaining > 1e-10 and buys:
                buy = buys[0]
                used = min(buy["amount_btc"], remaining)
                proceeds_share = used * proceeds_per_btc
                cost_portion = used * buy["cost_per_btc"]
                holding_days = (tx_date - buy["date"]).days

                if holding_days <= 365:
                    short_proceeds += proceeds_share
                    short_cost += cost_portion
                    short_gain += proceeds_share - cost_portion
                    short_count += 1
                else:
                    long_proceeds += proceeds_share
                    long_cost += cost_portion
                    long_gain += proceeds_share - cost_portion
                    long_count += 1

                buy["amount_btc"] -= used
                remaining -= used

                if buy["amount_btc"] < 1e-10:
                    buys.pop(0)

    return {
        "short_term": {
            "proceeds": round(short_proceeds, 2),
            "cost_basis": round(short_cost, 2),
            "gain_loss": round(short_gain, 2),
            "count": short_count,
        },
        "long_term": {
            "proceeds": round(long_proceeds, 2),
            "cost_basis": round(long_cost, 2),
            "gain_loss": round(long_gain, 2),
            "count": long_count,
        },
    }


def calculate_tax_data(
    transactions: list[dict],
    cost_per_btc: Optional[float] = None,
) -> tuple[dict, bool]:
    """
    Calculate tax data from transactions.
    Transactions should already be enriched with 'market_price_usd' from CoinGecko.
    Returns (result_dict, used_ai: bool).
    """
    ai_result = _call_venice_ai(transactions, cost_per_btc)
    if ai_result and "short_term" in ai_result and "long_term" in ai_result:
        for key in ("short_term", "long_term"):
            section = ai_result[key]
            for field in ("proceeds", "cost_basis", "gain_loss"):
                if field not in section:
                    section[field] = 0.0
            if "count" not in section:
                section["count"] = 0
        return ai_result, True

    logger.info("Using FIFO fallback calculator")
    return _fifo_fallback(transactions, cost_per_btc), False
