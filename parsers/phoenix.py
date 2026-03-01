"""
Phoenix Wallet CSV Parser
Expected columns: DATE, TYPE, AMOUNT MSAT, FEES MSAT, PAYMENT HASH, DESCRIPTION
"""
import csv
import io
from datetime import datetime, timezone

REQUIRED_COLS = {"DATE", "TYPE", "AMOUNT MSAT"}

MSAT_TO_BTC = 1e-11


def _validate(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Phoenix CSV is empty")
    cols = {k.strip().upper() for k in rows[0].keys()}
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(f"Phoenix CSV missing columns: {missing}")


def parse(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.strip()))
    rows = list(reader)
    _validate(rows)

    norm_rows = [{k.strip().upper(): v for k, v in row.items()} for row in rows]

    transactions = []
    for row in norm_rows:
        raw_date = row.get("DATE", "").strip()
        try:
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        amount_msat_raw = row.get("AMOUNT MSAT", "0").strip().replace(",", "") or "0"
        try:
            amount_msat = int(amount_msat_raw)
        except ValueError:
            continue

        fee_msat_raw = row.get("FEES MSAT", "0").strip().replace(",", "") or "0"
        try:
            fee_msat = abs(int(fee_msat_raw))
        except ValueError:
            fee_msat = 0

        tx_type_raw = row.get("TYPE", "").strip().lower()
        tx_type = "receive" if "receive" in tx_type_raw or amount_msat > 0 else "send"

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(amount_msat) * MSAT_TO_BTC, 8),
            "usd_value": 0.0,
            "fee_btc": round(fee_msat * MSAT_TO_BTC, 8),
            "tx_hash": row.get("PAYMENT HASH", "").strip(),
            "description": row.get("DESCRIPTION", "").strip(),
        })

    return transactions
