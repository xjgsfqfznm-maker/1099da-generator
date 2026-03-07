# 1099-DA Draft Generator

A privacy-first web application that helps U.S. Bitcoin holders generate a draft IRS Form 1099-DA from self-custodial wallet CSV exports.

## Supported Wallets

- **Sparrow** — on-chain Bitcoin wallet
- **Phoenix** — Lightning wallet (Acinq)
- **Zeus** — Lightning wallet
- **Muun** — hybrid on-chain/Lightning wallet
- **Wallet of Satoshi (WoS)** — custodial Lightning wallet

## Setup: Required Secrets

Set these in your Replit Secrets panel before running:

| Secret | Description |
|--------|-------------|
| `SESSION_SECRET` | Flask session signing key (generate any random string) |
| `VENICE_API_KEY` | Venice AI API key (get from venice.ai) |
| `CASHU_SEED` | BIP-39 seed phrase for persistent Cashu wallet (generate a 12-word mnemonic) |

### Generating a CASHU_SEED

Use any BIP-39 mnemonic generator, for example:
```
python3 -c "from mnemonic import Mnemonic; print(Mnemonic('english').generate(128))"
```

## How the Optional Donation Works

1. After uploading CSVs, a **200-satoshi Lightning invoice** is generated via the Cashu mint.
2. A QR code is displayed alongside the raw Lightning invoice string.
3. A **5-second countdown** starts automatically. After 5 seconds, the "Continue without paying" button is enabled.
4. If you pay, the app polls for confirmation every 3 seconds. Upon confirmation, you can continue immediately.
5. **The donation is completely optional** — skipping has no effect on functionality.

## Auto-Sweep Logic

When the Cashu wallet balance reaches **≥ 10,000 satoshis**, the entire balance is automatically swept to:

```
npub1c4ce67l50mycenl62vk2876a86tezg4kjmdetst0qu8gw942h99qtmpxej@npub.cash
```

The sweep runs:
- On each incoming request
- Every 5 minutes via a background thread

## Privacy Architecture

| Feature | Implementation |
|---------|----------------|
| No database | Session cookie (signed, server-side key) only |
| File handling | Read to RAM, immediately discarded — never written to disk |
| Session expiry | 10 minutes of inactivity |
| AI sanitization | tx_hash → SHA-256; descriptions stripped; timestamps → day only |
| Logging | HTTP method + endpoint only — no transaction data, no IPs |
| Security headers | X-Frame-Options DENY, CSP strict, nosniff |
| Rate limiting | 3 requests per IP per hour |

## User Flow

```
1. Privacy Notice → read and accept
2. Upload CSVs   → select wallet type, drag-and-drop up to 10 files
3. Donation      → optional 200-sat Lightning payment (5-second skip)
4. Processing    → CSV parse → AI tax calc → PDF build
5. Download      → draft_1099DA.pdf + tax_data.json
```

## Disclaimer

This tool generates **draft forms only** and is **not tax advice**. All calculations must be verified with a licensed CPA or tax professional before filing with the IRS. The generated form is not automatically submitted to the IRS.

## License

This project is licensed under the [MIT License](LICENSE).
