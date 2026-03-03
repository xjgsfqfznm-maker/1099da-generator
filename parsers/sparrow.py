"""
Sparrow Wallet CSV Parser

Handles both known Sparrow export formats:
  Format A (legacy): Date, Transaction Id, Label, Value (BTC), Fee (BTC)
  Format B (current): Date (UTC), Label, Value, Balance, Fee, Value (USD), Txid
                      — Value and Fee are in satoshis (integers)
                      — Lines starting with # are comments and are skipped
"""
import csv
import io
from datetime import datetime, timezone

SATS_TO_BTC = 1e-8


def _strip_comments(content: str) -> str:
    """Remove lines starting with # (Sparrow appends a disclaimer comment at the end)."""
    lines = [l for l in content.splitlines() if not l.strip().startswith("#")]
    return "\n".join(lines)


def _parse_date(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw or raw.lower() == "unconfirmed":
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S+00:00",
    ):
        try:
            dt = datetime.strptime(raw[:19], fmt[:len(fmt)])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse(content: str) -> list[dict]:
    content = _strip_comments(content)
    reader = csv.DictReader(io.StringIO(content.strip()))
    rows = list(reader)

    if not rows:
        raise ValueError("Sparrow CSV is empty")

    cols = {k.strip() for k in rows[0].keys()}

    # Detect format by checking for the satoshi-based column names
    is_sats_format = "Txid" in cols and "Value" in cols and "Value (BTC)" not in cols

    transactions = []
    for row in rows:
        # Normalize keys (strip whitespace)
        row = {k.strip(): v.strip() if v else "" for k, v in row.items()}

        # Date field differs by format
        raw_date = row.get("Date (UTC)", row.get("Date", ""))
        dt = _parse_date(raw_date)
        if dt is None:
            continue  # skip unconfirmed / unparseable rows

        if is_sats_format:
            # Value and Fee are in satoshis
            val_raw = row.get("Value", "0").replace(",", "") or "0"
            fee_raw = row.get("Fee", "0").replace(",", "") or "0"
            try:
                amount_sats = int(float(val_raw))
            except ValueError:
                continue
            try:
                fee_sats = abs(int(float(fee_raw)))
            except ValueError:
                fee_sats = 0

            amount_btc = amount_sats * SATS_TO_BTC
            fee_btc = fee_sats * SATS_TO_BTC

            usd_raw = row.get("Value (USD)", "0").replace(",", "").replace("$", "") or "0"
            try:
                usd_value = abs(float(usd_raw))
            except ValueError:
                usd_value = 0.0

            tx_hash = row.get("Txid", "")
        else:
            # Legacy format: Value (BTC), Fee (BTC), Transaction Id
            val_raw = row.get("Value (BTC)", "0").replace(",", "") or "0"
            fee_raw = row.get("Fee (BTC)", "0").replace(",", "") or "0"
            try:
                amount_btc = float(val_raw)
            except ValueError:
                continue
            try:
                fee_btc = abs(float(fee_raw))
            except ValueError:
                fee_btc = 0.0

            usd_value = 0.0
            tx_hash = row.get("Transaction Id", "")

        tx_type = "receive" if amount_btc >= 0 else "send"

        transactions.append({
            "date": dt.date().isoformat(),
            "type": tx_type,
            "amount_btc": round(abs(amount_btc), 8),
            "usd_value": round(usd_value, 2),
            "fee_btc": round(fee_btc, 8),
            "tx_hash": tx_hash.strip(),
            "description": row.get("Label", "").strip(),
        })

    return transactions
