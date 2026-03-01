"""
Sparrow Wallet CSV Parser
Expected columns: Date, Transaction Id, Label, Value (BTC), Fee (BTC)
"""
import csv
import io
from datetime import datetime, timezone


REQUIRED_COLS = {"Date", "Transaction Id", "Value (BTC)"}


def _validate(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Sparrow CSV is empty")
    cols = set(rows[0].keys())
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(f"Sparrow CSV missing columns: {missing}")


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
                dt = datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        amount_raw = row.get("Value (BTC)", "0").strip().replace(",", "")
        try:
            amount_btc = float(amount_raw)
        except ValueError:
            continue

        fee_raw = row.get("Fee (BTC)", "0").strip().replace(",", "") or "0"
        try:
            fee_btc = float(fee_raw)
        except ValueError:
            fee_btc = 0.0

        tx_type = "receive" if amount_btc >= 0 else "send"

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(amount_btc), 8),
            "usd_value": 0.0,
            "fee_btc": round(abs(fee_btc), 8),
            "tx_hash": row.get("Transaction Id", "").strip(),
            "description": row.get("Label", "").strip(),
        })

    return transactions
