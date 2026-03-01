"""
Zeus Wallet CSV Parser
Expected columns: Date, Type, Amount (sats), Fee (sats), Payment Hash / TX ID, Note
"""
import csv
import io
from datetime import datetime, timezone

REQUIRED_COLS = {"Date", "Type", "Amount (sats)"}
SATS_TO_BTC = 1e-8


def _validate(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Zeus CSV is empty")
    cols = set(rows[0].keys())
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(f"Zeus CSV missing columns: {missing}")


def parse(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.strip()))
    rows = list(reader)
    _validate(rows)

    transactions = []
    for row in rows:
        raw_date = row.get("Date", "").strip()
        try:
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        amount_raw = row.get("Amount (sats)", "0").strip().replace(",", "") or "0"
        try:
            amount_sats = int(amount_raw)
        except ValueError:
            continue

        fee_raw = row.get("Fee (sats)", "0").strip().replace(",", "") or "0"
        try:
            fee_sats = abs(int(fee_raw))
        except ValueError:
            fee_sats = 0

        tx_type_raw = row.get("Type", "").strip().lower()
        tx_type = "receive" if "receive" in tx_type_raw or amount_sats > 0 else "send"

        tx_hash = row.get("Payment Hash / TX ID", row.get("TX ID", "")).strip()

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(amount_sats) * SATS_TO_BTC, 8),
            "usd_value": 0.0,
            "fee_btc": round(fee_sats * SATS_TO_BTC, 8),
            "tx_hash": tx_hash,
            "description": row.get("Note", "").strip(),
        })

    return transactions
