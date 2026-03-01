"""
Muun Wallet CSV Parser
Expected columns: Date, Status, Is Swap, Amount (BTC), Amount (USD),
                  Network Fee (BTC), Lightning Fee (BTC), Transaction Id, Description
"""
import csv
import io
from datetime import datetime, timezone

REQUIRED_COLS = {"Date", "Amount (BTC)"}


def _validate(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Muun CSV is empty")
    cols = set(rows[0].keys())
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(f"Muun CSV missing columns: {missing}")


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

        amount_raw = row.get("Amount (BTC)", "0").strip().replace(",", "") or "0"
        try:
            amount_btc = float(amount_raw)
        except ValueError:
            continue

        usd_raw = row.get("Amount (USD)", "0").strip().replace(",", "").replace("$", "") or "0"
        try:
            usd_value = abs(float(usd_raw))
        except ValueError:
            usd_value = 0.0

        net_fee_raw = row.get("Network Fee (BTC)", "0").strip().replace(",", "") or "0"
        ln_fee_raw = row.get("Lightning Fee (BTC)", "0").strip().replace(",", "") or "0"
        try:
            fee_btc = abs(float(net_fee_raw)) + abs(float(ln_fee_raw))
        except ValueError:
            fee_btc = 0.0

        tx_type = "receive" if amount_btc >= 0 else "send"

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(amount_btc), 8),
            "usd_value": round(usd_value, 2),
            "fee_btc": round(fee_btc, 8),
            "tx_hash": row.get("Transaction Id", "").strip(),
            "description": row.get("Description", "").strip(),
        })

    return transactions
