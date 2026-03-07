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
DEFAULT_MINT = "https://mint.macadamia.cash"

SWEEP_ADDRESS = "npub1c4ce67l50mycenl62vk2876a86tezg4kjmdetst0qu8gw942h99qtmpxej@npub.cash"

# ── Single background event loop ───────────────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()

# Wallet singleton — set once and shared across all async calls
_wallet = None
_wallet_ready = threading.Event()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Return the running background event loop, creating it once."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(
                target=_loop.run_forever, daemon=True, name="cashu-loop"
            )
            _loop_thread.start()
    return _loop


def _run(coro, timeout: int = 90):
    """Submit a coroutine to the background loop and block until done."""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


# ── Wallet initialisation ──────────────────────────────────────────────────────

async def _init_wallet_async():
    global _wallet
    try:
        from cashu.wallet.wallet import Wallet
        seed = os.getenv("CASHU_SEED")
        mint_url = os.getenv("CASHU_MINT_URL", DEFAULT_MINT)

        kwargs = dict(
            url=mint_url,
            db="cashu_wallet_data",
            name="main",
        )
        if seed:
            kwargs["seed"] = seed
        else:
            kwargs["db"] = "cashu_wallet_demo"
            kwargs["name"] = "demo"
            logger.warning("CASHU_SEED not set — wallet running in demo mode")

        w = await Wallet.with_db(**kwargs)
        await w.load_mint()
        await w.load_proofs()
        _wallet = w
        logger.info(
            f"Cashu wallet ready — mint={mint_url} "
            f"balance={w.available_balance} sats"
        )
    except Exception as exc:
        logger.error(f"Cashu wallet init failed: {exc!r}")
        _wallet = None
    finally:
        _wallet_ready.set()


def init_wallet():
    """Initialise the wallet in the background. Call once at startup."""
    _ensure_loop()
    _run(_init_wallet_async(), timeout=60)


def get_wallet():
    """Return the wallet instance (or None if unavailable)."""
    _wallet_ready.wait(timeout=30)
    return _wallet


# ── Invoice creation ───────────────────────────────────────────────────────────

async def _create_invoice_async(amount_sats: int) -> dict:
    w = _wallet
    if w is None:
        raise RuntimeError("Cashu wallet not available")
    mint_quote = await w.request_mint(amount_sats)
    return {
        "payment_request": mint_quote.request,
        "quote_id": mint_quote.quote,
        "amount_sats": amount_sats,
    }


def create_invoice(amount_sats: int = DONATION_SATS, memo: str = "") -> dict:
    """Create a Lightning invoice. Returns {payment_request, quote_id, amount_sats}."""
    return _run(_create_invoice_async(amount_sats))


# ── Payment check ──────────────────────────────────────────────────────────────

async def _check_payment_async(quote_id: str) -> bool:
    w = _wallet
    if w is None:
        return False
    try:
        from cashu.core.base import MintQuoteState
        quote = await w.get_mint_quote(quote_id)
        if hasattr(quote, "state") and quote.state == MintQuoteState.paid:
            await w.mint(DONATION_SATS, quote_id=quote_id)
            await w.load_proofs()
            return True
        return False
    except Exception as exc:
        logger.error(f"Check payment failed: {exc!r}")
        return False


def check_payment(quote_id: str) -> bool:
    """Return True if the invoice has been paid and tokens minted."""
    try:
        return _run(_check_payment_async(quote_id))
    except Exception as exc:
        logger.error(f"Payment check error: {exc!r}")
        return False


# ── Balance ────────────────────────────────────────────────────────────────────

async def _get_balance_async() -> int:
    w = _wallet
    if w is None:
        return 0
    try:
        await w.load_proofs()
        return int(w.available_balance)
    except Exception as exc:
        logger.error(f"Balance check failed: {exc!r}")
        return 0


def get_balance() -> int:
    try:
        return _run(_get_balance_async())
    except Exception as exc:
        logger.error(f"Balance error: {exc!r}")
        return 0


# ── Auto-sweep ─────────────────────────────────────────────────────────────────

async def _sweep_async() -> Optional[str]:
    w = _wallet
    if w is None:
        return None
    try:
        balance = await _get_balance_async()
        if balance < SWEEP_THRESHOLD_SATS:
            return None
        logger.info(f"Sweep triggered: {balance} sats >= {SWEEP_THRESHOLD_SATS}")
        melt_quote = await w.get_melt_quote(request=SWEEP_ADDRESS, unit="sat")
        result = await w.melt(melt_quote)
        logger.info(f"Sweep complete: {result}")
        return str(result)
    except Exception as exc:
        logger.error(f"Auto-sweep failed: {exc!r}")
        return None


def check_and_sweep() -> Optional[str]:
    """Check balance and sweep if threshold is met. Safe to call from any thread."""
    try:
        result = _run(_sweep_async())
        if result:
            logger.info(f"Auto-sweep executed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Sweep check error: {exc!r}")
        return None


def start_sweep_background_thread():
    """Start a daemon thread that periodically checks and sweeps."""
    import time

    def sweep_loop():
        while True:
            try:
                check_and_sweep()
            except Exception as exc:
                logger.error(f"Sweep loop error: {exc!r}")
            time.sleep(300)

    t = threading.Thread(target=sweep_loop, daemon=True, name="cashu-sweep")
    t.start()
    logger.info("Auto-sweep background thread started")
