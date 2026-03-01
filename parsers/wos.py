"""
Wallet of Satoshi (WoS) CSV Parser
Expected columns: Date, Memo, USD, Sats, Type
"""
import csv
import io
from datetime import datetime, timezone

REQUIRED_COLS = {"Date", "Sats", "Type"}
SATS_TO_BTC = 1e-8


def _validate(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("WoS CSV is empty")
    cols = set(rows[0].keys())
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(f"WoS CSV missing columns: {missing}")


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
                for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                    try:
                        dt = datetime.strptime(raw_date, fmt)
                        dt = dt.replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    continue
            except Exception:
                continue

        sats_raw = row.get("Sats", "0").strip().replace(",", "") or "0"
        try:
            sats = int(sats_raw)
        except ValueError:
            continue

        usd_raw = row.get("USD", "0").strip().replace(",", "").replace("$", "") or "0"
        try:
            usd_value = abs(float(usd_raw))
        except ValueError:
            usd_value = 0.0

        tx_type_raw = row.get("Type", "").strip().lower()
        tx_type = "receive" if "receive" in tx_type_raw or sats > 0 else "send"

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(sats) * SATS_TO_BTC, 8),
            "usd_value": round(usd_value, 2),
            "fee_btc": 0.0,
            "tx_hash": row.get("Transaction Id", row.get("Hash", "")).strip(),
            "description": row.get("Memo", "").strip(),
        })

    return transactions
