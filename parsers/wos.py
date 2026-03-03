"""
Wallet of Satoshi (WoS) CSV Parser

Handles both known WoS export formats:
  Format A (legacy):  Date, Memo, USD, Sats, Type
  Format B (current): utcDate, type, currency, amount, fees, status,
                       address, description, transactionId, pointOfSale
                       — amount and fees are in BTC (float)
                       — type is DEBIT (send) or CREDIT (receive)
"""
import csv
import io
from datetime import datetime, timezone

SATS_TO_BTC = 1e-8


def _parse_date(raw: str) -> datetime | None:
    raw = raw.strip().strip('"')
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def parse(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.strip()))
    rows = list(reader)

    if not rows:
        raise ValueError("WoS CSV is empty")

    # Normalize column names (strip quotes and whitespace)
    norm_rows = [{k.strip().strip('"'): v.strip().strip('"') for k, v in row.items()} for row in rows]
    cols = set(norm_rows[0].keys())

    # Detect format: current format has 'utcDate' and 'transactionId'
    is_current_format = "utcDate" in cols and "transactionId" in cols

    transactions = []
    for row in norm_rows:
        if is_current_format:
            raw_date = row.get("utcDate", "")
            dt = _parse_date(raw_date)
            if dt is None:
                continue

            amount_raw = row.get("amount", "0").replace(",", "") or "0"
            fees_raw = row.get("fees", "0").replace(",", "") or "0"
            try:
                amount_btc = float(amount_raw)
            except ValueError:
                continue
            try:
                fee_btc = abs(float(fees_raw))
            except ValueError:
                fee_btc = 0.0

            tx_type_raw = row.get("type", "").upper()
            tx_type = "receive" if tx_type_raw == "CREDIT" else "send"

            tx_hash = row.get("transactionId", "").strip()
            description = row.get("description", "").strip()
            usd_value = 0.0

        else:
            # Legacy format: Date, Sats, Type, Memo, USD
            raw_date = row.get("Date", "")
            dt = _parse_date(raw_date)
            if dt is None:
                continue

            sats_raw = row.get("Sats", "0").replace(",", "") or "0"
            try:
                sats = int(sats_raw)
            except ValueError:
                continue

            usd_raw = row.get("USD", "0").replace(",", "").replace("$", "") or "0"
            try:
                usd_value = abs(float(usd_raw))
            except ValueError:
                usd_value = 0.0

            tx_type_raw = row.get("Type", "").lower()
            tx_type = "receive" if "receive" in tx_type_raw or sats > 0 else "send"

            amount_btc = abs(sats) * SATS_TO_BTC
            fee_btc = 0.0
            tx_hash = row.get("Transaction Id", row.get("Hash", "")).strip()
            description = row.get("Memo", "").strip()

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(amount_btc), 8),
            "usd_value": round(usd_value, 2),
            "fee_btc": round(fee_btc, 8),
            "tx_hash": tx_hash,
            "description": description,
        })

    return transactions
