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

# Column signatures used for auto-detection (all must be present in the CSV header)
_SIGNATURES = {
    "sparrow":  {"Transaction Id", "Value (BTC)"},
    "muun":     {"Amount (BTC)", "Network Fee (BTC)"},
    "phoenix":  {"AMOUNT MSAT"},
    "zeus":     {"Amount (sats)"},
    "wos":      {"Sats", "Memo"},
}


def detect_wallet_type(content: str) -> str:
    """
    Inspect the CSV header row and return the matching wallet type key.
    Raises ValueError if no wallet type can be determined.
    """
    try:
        reader = csv.reader(io.StringIO(content.strip()))
        header = {col.strip().upper() for col in next(reader)}
    except StopIteration:
        raise ValueError("CSV file appears to be empty")

    for wallet_type, required_cols in _SIGNATURES.items():
        if all(col.upper() in header for col in required_cols):
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
