# 1099-DA Draft Generator

## Architecture

**Stack:** Python 3.11 + Flask (backend), HTML5 + Vanilla JS (frontend), ReportLab (PDF), Venice AI / kimi-k2-5 (AI), Cashu (payments)

**No database** — entirely in-memory/session-based.

## File Structure

```
main.py                    Flask app: routes /, /upload, /donate, /check-payment, /generate, /download/*
parsers/
  __init__.py              Dispatcher — routes wallet_type to correct parser
  sparrow.py               Sparrow Wallet CSV parser
  phoenix.py               Phoenix Wallet CSV parser
  zeus.py                  Zeus Wallet CSV parser
  muun.py                  Muun Wallet CSV parser
  wos.py                   Wallet of Satoshi CSV parser
utils/
  __init__.py
  cashu_wallet.py          Persistent Cashu wallet wrapper + auto-sweep logic
  ai_client.py             Venice AI client + FIFO fallback calculator
  pdf_builder.py           ReportLab IRS 1099-DA PDF layout
templates/
  index.html               Single-page UI (5-step flow)
static/
  style.css                Bitcoin orange theme
  script.js                Client-side SPA logic
requirements.txt
README.md
```

## Required Secrets

| Secret | Purpose |
|--------|---------|
| `SESSION_SECRET` | Flask session signing key |
| `VENICE_API_KEY` | Venice AI API key |
| `CASHU_SEED` | BIP-39 seed phrase for persistent Cashu wallet |

## Key Features

- **CSV Parsers:** Sparrow, Phoenix, Zeus, Muun, Wallet of Satoshi — all normalize to `{date, type, amount_btc, usd_value, fee_btc, tx_hash, description}`
- **Privacy:** No database, session-only storage, files read to RAM and immediately discarded, 10-minute session expiry
- **Security headers:** X-Frame-Options DENY, CSP strict, nosniff, no-store cache
- **Rate limiting:** 3 requests/IP/hour via flask-limiter
- **AI:** Venice AI kimi-k2-5 with sanitization (SHA-256 hashed tx_hash, stripped descriptions); FIFO fallback if AI unavailable
- **Cashu wallet:** Persistent via CASHU_SEED secret; auto-sweep to Lightning address when balance ≥ 10,000 sats
- **PDF:** Draft IRS 1099-DA with watermark "DRAFT - VERIFY ALL CALCULATIONS"; boxes 1a-1g, 2, 3 filled; personal fields left blank

## Port

App runs on port **5000**.
