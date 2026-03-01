"""
Cashu Persistent Wallet Wrapper

PRIVACY: This module handles Cashu ecash tokens only.
No transaction data or user PII is ever stored here.

The wallet seed is loaded from the CASHU_SEED environment secret,
making the wallet persistent across restarts. Proofs are stored in
a local SQLite database managed by the cashu library.

AUTO-SWEEP: When the wallet balance reaches >= 10,000 sats, the
entire balance is swept to the configured Lightning address.
"""
import asyncio
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

SWEEP_THRESHOLD_SATS = 10_000
DONATION_SATS = 200
DEFAULT_MINT = "https://mint.minibits.cash/Bitcoin"

SWEEP_ADDRESS = "npub1c4ce67l50mycenl62vk2876a86tezg4kjmdetst0qu8gw942h99qtmpxej@npub.cash"

_wallet_lock = threading.Lock()
_wallet_instance = None
_loop = None


def _get_or_create_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def _run_async(coro):
    """Run an async coroutine in the background event loop (thread-safe)."""
    loop = _get_or_create_loop()
    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=60)
    else:
        return loop.run_until_complete(coro)


def _start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_background_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        t = threading.Thread(target=_start_background_loop, args=(_loop,), daemon=True)
        t.start()
    return _loop


def run_in_background(coro):
    loop = _get_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=90)


async def _init_wallet():
    """Initialize the Cashu wallet with the seed from environment secrets."""
    try:
        from cashu.wallet.wallet import Wallet
        seed = os.getenv("CASHU_SEED")
        mint_url = os.getenv("CASHU_MINT_URL", DEFAULT_MINT)

        if not seed:
            logger.warning("CASHU_SEED not set — wallet running in demo mode (no persistence)")
            wallet = await Wallet.with_db(
                url=mint_url,
                db="cashu_wallet_demo",
                name="demo",
            )
        else:
            wallet = await Wallet.with_db(
                url=mint_url,
                db="cashu_wallet_data",
                name="main",
                seed=seed,
            )

        await wallet.load_mint()
        await wallet.load_proofs()
        return wallet
    except Exception as e:
        logger.error(f"Cashu wallet init failed: {e}")
        return None


def get_wallet():
    """Get or initialize the wallet singleton."""
    global _wallet_instance
    with _wallet_lock:
        if _wallet_instance is None:
            try:
                _wallet_instance = run_in_background(_init_wallet())
            except Exception as e:
                logger.error(f"Wallet initialization error: {e}")
                _wallet_instance = None
    return _wallet_instance


async def _create_invoice_async(amount_sats: int, memo: str) -> dict:
    """Create a Lightning invoice for the given amount."""
    wallet = get_wallet()
    if wallet is None:
        raise RuntimeError("Cashu wallet not available")

    try:
        mint_quote = await wallet.request_mint(amount_sats)
        return {
            "payment_request": mint_quote.request,
            "quote_id": mint_quote.quote,
            "amount_sats": amount_sats,
        }
    except Exception as e:
        logger.error(f"Create invoice failed: {e}")
        raise


def create_invoice(amount_sats: int = DONATION_SATS, memo: str = "Optional donation to cover server costs") -> dict:
    """Create a 200-sat Lightning invoice. Returns {payment_request, quote_id, amount_sats}."""
    return run_in_background(_create_invoice_async(amount_sats, memo))


async def _check_payment_async(quote_id: str) -> bool:
    """Check if a mint quote has been paid."""
    wallet = get_wallet()
    if wallet is None:
        return False

    try:
        from cashu.core.base import MintQuoteState
        quote = await wallet.get_mint_quote(quote_id)
        if hasattr(quote, 'state') and quote.state == MintQuoteState.paid:
            await wallet.mint(wallet.available_balance + DONATION_SATS, quote_id=quote_id)
            await wallet.load_proofs()
            return True
        return False
    except Exception as e:
        logger.error(f"Check payment failed: {e}")
        return False


def check_payment(quote_id: str) -> bool:
    """Return True if the invoice has been paid and tokens minted."""
    try:
        return run_in_background(_check_payment_async(quote_id))
    except Exception as e:
        logger.error(f"Payment check error: {e}")
        return False


async def _get_balance_async() -> int:
    """Get wallet balance in satoshis."""
    wallet = get_wallet()
    if wallet is None:
        return 0
    try:
        await wallet.load_proofs()
        return wallet.available_balance
    except Exception as e:
        logger.error(f"Balance check failed: {e}")
        return 0


def get_balance() -> int:
    """Get wallet balance in satoshis."""
    try:
        return run_in_background(_get_balance_async())
    except Exception as e:
        logger.error(f"Balance error: {e}")
        return 0


async def _sweep_async() -> Optional[str]:
    """
    AUTO-SWEEP: If balance >= SWEEP_THRESHOLD_SATS, pay out the entire balance
    to the configured Lightning address.
    Returns the payment result string or None.
    """
    wallet = get_wallet()
    if wallet is None:
        return None

    try:
        balance = await _get_balance_async()
        if balance < SWEEP_THRESHOLD_SATS:
            return None

        logger.info(f"Sweep triggered: balance={balance} sats >= threshold={SWEEP_THRESHOLD_SATS}")

        melt_quote = await wallet.get_melt_quote(
            request=SWEEP_ADDRESS,
            unit="sat",
        )
        result = await wallet.melt(melt_quote)
        logger.info(f"Sweep complete: {result}")
        return str(result)
    except Exception as e:
        logger.error(f"Auto-sweep failed: {e}")
        return None


def check_and_sweep():
    """Check balance and sweep if threshold is met. Safe to call from any thread."""
    try:
        result = run_in_background(_sweep_async())
        if result:
            logger.info(f"Auto-sweep executed: {result}")
        return result
    except Exception as e:
        logger.error(f"Sweep check error: {e}")
        return None


def start_sweep_background_thread():
    """Start a background thread that periodically checks and sweeps."""
    import time

    def sweep_loop():
        while True:
            try:
                check_and_sweep()
            except Exception as e:
                logger.error(f"Sweep loop error: {e}")
            time.sleep(300)

    t = threading.Thread(target=sweep_loop, daemon=True)
    t.start()
    logger.info("Auto-sweep background thread started")
