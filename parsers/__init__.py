import csv
import io

from parsers.sparrow import parse as parse_sparrow
from parsers.phoenix import parse as parse_phoenix
from parsers.zeus import parse as parse_zeus
from parsers.muun import parse as parse_muun
from parsers.wos import parse as parse_wos

PARSERS = {
    "sparrow": parse_sparrow,
    "phoenix": parse_phoenix,
    "zeus": parse_zeus,
    "muun": parse_muun,
    "wos": parse_wos,
}

WALLET_LABELS = {
    "sparrow": "Sparrow Wallet",
    "phoenix": "Phoenix Wallet",
    "zeus": "Zeus Wallet",
    "muun": "Muun Wallet",
    "wos": "Wallet of Satoshi",
}

# Column signatures for auto-detection.
# Each wallet maps to a list of possible signature sets (any one match is sufficient).
# All columns in a set must be present in the header (case-insensitive).
_SIGNATURES: dict[str, list[set[str]]] = {
    "sparrow": [
        {"Txid", "Date (UTC)"},           # Current Sparrow export (satoshi-based)
        {"Transaction Id", "Value (BTC)"}, # Legacy Sparrow export (BTC-based)
    ],
    "muun": [
        {"Amount (BTC)", "Network Fee (BTC)"},
    ],
    "phoenix": [
        {"Amount Msat"},
        {"AMOUNT MSAT"},
    ],
    "zeus": [
        {"Amount (sats)"},
    ],
    "wos": [
        {"utcDate", "transactionId"},  # Current WoS self-custody export
        {"Sats", "Memo"},              # Legacy WoS export
    ],
}


def detect_wallet_type(content: str) -> str:
    """
    Inspect the CSV header row and return the matching wallet type key.
    Skips comment lines (starting with #) before reading the header.
    Raises ValueError if no wallet type can be determined.
    """
    # Strip comment lines Sparrow appends at the bottom / top
    clean_lines = [l for l in content.splitlines() if not l.strip().startswith("#")]
    clean = "\n".join(clean_lines)

    try:
        reader = csv.reader(io.StringIO(clean.strip()))
        raw_header = next(reader)
    except StopIteration:
        raise ValueError("CSV file appears to be empty")

    header = {col.strip().strip('"').upper() for col in raw_header}

    for wallet_type, sig_list in _SIGNATURES.items():
        for sig_set in sig_list:
            if all(col.upper() in header for col in sig_set):
                return wallet_type

    raise ValueError(
        "Could not identify wallet type from CSV headers. "
        "Supported wallets: Sparrow, Phoenix, Zeus, Muun, Wallet of Satoshi."
    )


def parse_csv(content: str, wallet_type: str = None) -> tuple[list[dict], str]:
    """
    Parse CSV content and return (transactions, detected_wallet_type).
    If wallet_type is not provided, it is auto-detected from the headers.
    Each transaction: {date, type, amount_btc, usd_value, fee_btc, tx_hash, description}
    """
    if not wallet_type:
        wallet_type = detect_wallet_type(content)

    if wallet_type not in PARSERS:
        raise ValueError(f"Unknown wallet type: {wallet_type}")

    return PARSERS[wallet_type](content), wallet_type
