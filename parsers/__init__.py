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


def parse_csv(wallet_type: str, content: str) -> list[dict]:
    """
    Dispatch to the correct parser and return normalized transaction list.
    Each transaction: {date, type, amount_btc, usd_value, fee_btc, tx_hash, description}
    """
    if wallet_type not in PARSERS:
        raise ValueError(f"Unknown wallet type: {wallet_type}")
    return PARSERS[wallet_type](content)
