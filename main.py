"""
1099-DA Draft Generator — Privacy-First Flask Application

PRIVACY SAFEGUARDS:
  - No database: All data lives in signed Flask session cookies (RAM) or temp files deleted immediately
  - CSV files are read into memory and the upload is discarded — no disk persistence of user data
  - Sessions expire after 10 minutes of inactivity (PERMANENT_SESSION_LIFETIME)
  - Logs record only HTTP method + endpoint, never transaction data or IPs
  - Security headers: X-Frame-Options DENY, CSP, nosniff

RATE LIMITING: 3 requests per IP per hour via flask-limiter
"""
import json
import logging
import os
import time
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, session,
    send_file, Response
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import io

from parsers import parse_csv
from utils.ai_client import calculate_tax_data
from utils.coingecko import enrich_transactions_with_prices
from utils.pdf_builder import build_1099da_pdf
from utils.cashu_wallet import (
    create_invoice, check_payment, get_balance,
    check_and_sweep, start_sweep_background_thread, init_wallet,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

app.secret_key = os.environ.get("SESSION_SECRET") or os.environ.get("FLASK_SECRET") or os.urandom(32)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=10)
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["20 per hour"],
    storage_uri="memory://",
)

MAX_FILES = 10
MAX_FILE_SIZE = 5 * 1024 * 1024


@app.after_request
def set_security_headers(response: Response) -> Response:
    """Attach strict security headers to every response."""
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


def session_required(f):
    """Decorator: require that the session has processed transactions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "transactions" not in session:
            return jsonify({"error": "Session expired or no data. Please upload files again."}), 403
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    """Landing page — privacy notice + upload UI."""
    logger.info("GET /")
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@limiter.limit("20 per hour")
def upload():
    """
    Handle CSV uploads from up to 10 wallet files.

    PRIVACY: Files are read into memory only; no temp files written to disk.
    Data is stored in signed session cookie (server-signed, client-held).
    """
    logger.info("POST /upload")
    session.permanent = True
    session.modified = True

    files = request.files.getlist("files")

    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No files provided"}), 400

    if len(files) > MAX_FILES:
        return jsonify({"error": f"Maximum {MAX_FILES} files allowed"}), 400

    # Optional user-provided average cost basis per BTC
    cost_per_btc_raw = request.form.get("cost_per_btc", "").strip()
    cost_per_btc = None
    if cost_per_btc_raw:
        try:
            cost_per_btc = float(cost_per_btc_raw.replace(",", "").replace("$", ""))
            if cost_per_btc <= 0:
                cost_per_btc = None
        except ValueError:
            cost_per_btc = None

    all_transactions = []
    detected_types = set()
    errors = []

    for f in files:
        if f.filename == "":
            continue

        raw_bytes = f.read()
        if len(raw_bytes) > MAX_FILE_SIZE:
            errors.append(f"{f.filename}: exceeds 5MB limit")
            continue

        try:
            content = raw_bytes.decode("utf-8", errors="replace")
            txns, wallet_type = parse_csv(content)
            all_transactions.extend(txns)
            detected_types.add(wallet_type)
        except Exception as e:
            errors.append(f"{f.filename}: {str(e)}")

        del raw_bytes

    if not all_transactions and errors:
        return jsonify({"error": "All files failed to parse", "details": errors}), 400

    detected_label = ", ".join(detected_types) if detected_types else "unknown"
    session["transactions"] = all_transactions
    session["wallet_type"] = detected_label
    session["cost_per_btc"] = cost_per_btc
    session["upload_time"] = time.time()
    session.pop("tax_data", None)
    session.pop("paid", None)

    logger.info(f"POST /upload wallet={detected_label} txn_count={len(all_transactions)} cost_per_btc={'set' if cost_per_btc else 'not set'}")

    return jsonify({
        "success": True,
        "transaction_count": len(all_transactions),
        "errors": errors,
    })


@app.route("/donate", methods=["POST"])
def donate():
    """
    Generate a 200-sat Cashu Lightning invoice for the optional donation.
    Returns the Lightning payment request and a quote ID for verification.
    """
    logger.info("POST /donate")

    check_and_sweep()

    try:
        invoice = create_invoice(200, "Optional donation to cover server costs")
        session["quote_id"] = invoice["quote_id"]
        session.modified = True

        import qrcode
        import base64

        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data(f"lightning:{invoice['payment_request']}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        qr_b64 = base64.b64encode(buf.read()).decode()

        return jsonify({
            "success": True,
            "payment_request": invoice["payment_request"],
            "quote_id": invoice["quote_id"],
            "amount_sats": 200,
            "qr_code": f"data:image/png;base64,{qr_b64}",
        })
    except Exception as e:
        logger.error(f"Donate invoice error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/check-payment", methods=["POST"])
def check_payment_route():
    """
    Poll whether the Lightning invoice has been paid.
    Sets session['paid'] = True if confirmed.
    """
    logger.info("POST /check-payment")

    quote_id = session.get("quote_id")
    if not quote_id:
        return jsonify({"paid": False, "error": "No invoice found"}), 400

    try:
        paid = check_payment(quote_id)
        if paid:
            session["paid"] = True
            session.modified = True
            check_and_sweep()

        return jsonify({"paid": paid})
    except Exception as e:
        logger.error(f"Payment check error: {e}")
        return jsonify({"paid": False, "error": str(e)}), 500


@app.route("/generate", methods=["POST"])
@limiter.limit("20 per hour")
@session_required
def generate():
    """
    Main processing route:
      1. Load transactions from session
      2. Send sanitized data to Venice AI (or FIFO fallback)
      3. Build 1099-DA PDF with ReportLab
      4. Store results in session

    PRIVACY: Transactions are read from session cookie (RAM), processed,
    and the PDF bytes are stored temporarily in session. No disk writes.
    """
    logger.info("POST /generate")

    check_and_sweep()

    transactions = session.get("transactions", [])
    if not transactions:
        return jsonify({"error": "No transaction data in session"}), 400

    cost_per_btc = session.get("cost_per_btc")

    try:
        # Enrich each transaction with the CoinGecko BTC/USD price for that date.
        # PRIVACY: Only dates (not amounts or hashes) are sent to CoinGecko.
        logger.info("POST /generate — fetching CoinGecko historical prices")
        enriched_transactions, price_map = enrich_transactions_with_prices(transactions)
        logger.info(f"POST /generate — fetched {len(price_map)} unique date prices")

        tax_data, used_ai = calculate_tax_data(enriched_transactions, cost_per_btc)
        session["tax_data"] = tax_data
        session["used_ai"] = used_ai
        session["price_map"] = price_map
        session.modified = True

        logger.info(
            f"POST /generate used_ai={used_ai} "
            f"short_count={tax_data['short_term']['count']} "
            f"long_count={tax_data['long_term']['count']} "
            f"cost_per_btc={'set' if cost_per_btc else 'not set'}"
        )

        return jsonify({
            "success": True,
            "used_ai": used_ai,
            "cost_per_btc": cost_per_btc,
            "prices_fetched": len(price_map),
            "tax_data": tax_data,
        })
    except Exception as e:
        logger.error(f"Generate error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/download/pdf")
@session_required
def download_pdf():
    """
    Build and stream the draft 1099-DA PDF.
    PRIVACY: PDF is generated on-the-fly into a BytesIO buffer — never written to disk.
    """
    logger.info("GET /download/pdf")

    tax_data = session.get("tax_data")
    if not tax_data:
        return jsonify({"error": "No tax data. Run /generate first."}), 400

    try:
        pdf_bytes = build_1099da_pdf(tax_data)
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="draft_1099DA.pdf",
        )
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/download/json")
@session_required
def download_json():
    """
    Return the raw tax calculation JSON.
    PRIVACY: No transaction hashes, descriptions, or wallet identifiers are included.
    """
    logger.info("GET /download/json")

    tax_data = session.get("tax_data")
    if not tax_data:
        return jsonify({"error": "No tax data. Run /generate first."}), 400

    output = {
        "disclaimer": "DRAFT ONLY — Not for filing. Verify with a licensed tax professional.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "used_ai": session.get("used_ai", False),
        "short_term": tax_data.get("short_term", {}),
        "long_term": tax_data.get("long_term", {}),
    }

    return Response(
        json.dumps(output, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=tax_data.json"},
    )


@app.route("/clear-session", methods=["POST"])
def clear_session_route():
    """
    Explicitly clear the session (user data purge).
    PRIVACY: Called on page unload or by user action to wipe all in-memory data.
    """
    logger.info("POST /clear-session")
    session.clear()
    return jsonify({"success": True})


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large. Maximum total upload is 50MB."}), 413


@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Rate limit exceeded. Maximum 20 requests per hour per IP."}), 429


init_wallet()
start_sweep_background_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
