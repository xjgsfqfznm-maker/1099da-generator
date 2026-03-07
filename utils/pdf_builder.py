"""
IRS Form 1099-DA PDF Builder

PDF BOX MAPPING (IRS 1099-DA draft layout):
  Box 1a: Date of acquisition (from short-term/long-term gain data)
  Box 1b: Date of sale or disposition
  Box 1c: Proceeds (USD)
  Box 1d: Cost or other basis (USD)
  Box 1e: Adjustment codes
  Box 1f: Adjustment amount
  Box 1g: Net gain or loss
  Box 2:  Short-term / long-term indicator
  Box 3:  Check if proceeds from collectibles

BLANK FIELDS: Payer/Recipient name, address, TIN, and account number are left blank
              for the user to fill in manually.

PRIVACY: No wallet addresses, transaction hashes, or identifiers appear in the PDF.
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


BTC_ORANGE = colors.HexColor("#F7931A")
DARK_GRAY = colors.HexColor("#333333")
LIGHT_GRAY = colors.HexColor("#F5F5F5")
MID_GRAY = colors.HexColor("#CCCCCC")
WHITE = colors.white
BLACK = colors.black

# Disposition table column definitions: (header, width_pt, alignment)
_COLS = [
    ("#",            22, "L"),
    ("Acq. Date",    70, "L"),
    ("Sale Date",    70, "L"),
    ("Amount BTC",   75, "R"),
    ("Proceeds",    101, "R"),
    ("Cost Basis",  101, "R"),
    ("Gain/(Loss)", 101, "R"),
]
_TOTAL_COL_W = sum(c[1] for c in _COLS)  # 540pt == content_width
_ROW_H = 13   # data row height
_HDR_H = 16   # column header row height


def _draw_box(c: canvas.Canvas, x, y, w, h, label: str, value: str, label_size=6, value_size=9) -> None:
    """Draw a labelled form box."""
    c.setStrokeColor(MID_GRAY)
    c.setFillColor(WHITE)
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(DARK_GRAY)
    c.setFont("Helvetica", label_size)
    c.drawString(x + 3, y + h - label_size - 2, label)
    c.setFont("Helvetica-Bold", value_size)
    c.setFillColor(BLACK)
    c.drawString(x + 3, y + 5, value[:40] if value else "")


def _draw_footer(c: canvas.Canvas, width: float, footer_y: float) -> None:
    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(width / 2, footer_y,
                        "Generated from self-custodial wallet data. "
                        "NOT tax advice. Verify with a qualified CPA or tax professional. "
                        "This form is not submitted to the IRS.")


def _max_rows_fitting(start_y: float, footer_y: float) -> int:
    """How many data rows fit between start_y and footer_y given table overhead."""
    overhead = 14 + 4 + _HDR_H + 4  # title + separator + header row + gap
    available = start_y - footer_y - overhead
    return max(0, int(available / _ROW_H))


def _draw_disposition_chunk(
    c: canvas.Canvas,
    page_rows: list,
    all_section_rows: list,
    start_y: float,
    margin: float,
    section_label: str,
    row_offset: int,
    is_continuation: bool,
    is_last_page: bool,
) -> None:
    """
    Draw one page-worth of disposition rows.

    page_rows       — the rows to render on this page
    all_section_rows— full section list (used for the totals row)
    start_y         — y coordinate to start drawing from
    row_offset      — how many rows have already been printed (for # numbering)
    is_last_page    — whether to append the totals row after these rows
    """
    y = start_y

    # Table title
    title = (
        f"DISPOSITION DETAIL (continued) — {section_label}"
        if is_continuation
        else f"DISPOSITION DETAIL — {section_label}"
    )
    c.setFillColor(BTC_ORANGE)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin, y, title)
    y -= 4
    c.setStrokeColor(BTC_ORANGE)
    c.setLineWidth(0.5)
    c.line(margin, y, margin + _TOTAL_COL_W, y)
    y -= 2

    # Column headers
    x_cursor = margin
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(DARK_GRAY)
    for col_label, col_w, align in _COLS:
        if align == "R":
            c.drawRightString(x_cursor + col_w - 2, y - _HDR_H + 5, col_label)
        else:
            c.drawString(x_cursor + 2, y - _HDR_H + 5, col_label)
        x_cursor += col_w
    y -= _HDR_H
    c.setStrokeColor(MID_GRAY)
    c.setLineWidth(0.4)
    c.line(margin, y, margin + _TOTAL_COL_W, y)
    y -= 2

    # Data rows
    for local_idx, row in enumerate(page_rows):
        row_y = y - _ROW_H
        global_num = row_offset + local_idx + 1

        # Alternating stripe
        if local_idx % 2 == 0:
            c.setFillColor(LIGHT_GRAY)
            c.rect(margin, row_y, _TOTAL_COL_W, _ROW_H, fill=1, stroke=0)

        gain = row.get("gain_loss", 0.0)
        gain_color = colors.HexColor("#C62828") if gain < 0 else colors.HexColor("#1B5E20")

        row_vals = [
            (str(global_num),                        "L", DARK_GRAY),
            (row.get("acq_date", ""),                "L", DARK_GRAY),
            (row.get("sale_date", ""),               "L", DARK_GRAY),
            (f"{row.get('amount_btc', 0):.8f}",      "R", DARK_GRAY),
            (f"${row.get('proceeds', 0):,.2f}",      "R", DARK_GRAY),
            (f"${row.get('cost_basis', 0):,.2f}",    "R", DARK_GRAY),
            (f"${gain:,.2f}",                        "R", gain_color),
        ]

        x_cursor = margin
        c.setFont("Helvetica", 7)
        for (val, align, col_color), (_, col_w, _) in zip(row_vals, _COLS):
            c.setFillColor(col_color)
            if align == "R":
                c.drawRightString(x_cursor + col_w - 2, row_y + 3, val)
            else:
                c.drawString(x_cursor + 2, row_y + 3, val)
            x_cursor += col_w

        y -= _ROW_H

    # Bottom border
    c.setStrokeColor(MID_GRAY)
    c.setLineWidth(0.4)
    c.line(margin, y, margin + _TOTAL_COL_W, y)

    # Totals row — only on the final page of this section's dispositions
    if is_last_page:
        y -= 1
        tot_proceeds = sum(r.get("proceeds", 0.0) for r in all_section_rows)
        tot_cost     = sum(r.get("cost_basis", 0.0) for r in all_section_rows)
        tot_gain     = sum(r.get("gain_loss", 0.0) for r in all_section_rows)
        tot_color    = colors.HexColor("#C62828") if tot_gain < 0 else colors.HexColor("#1B5E20")

        totals_vals = [
            ("TOTAL",             "L", DARK_GRAY),
            ("",                  "L", DARK_GRAY),
            ("",                  "L", DARK_GRAY),
            ("",                  "R", DARK_GRAY),
            (f"${tot_proceeds:,.2f}", "R", DARK_GRAY),
            (f"${tot_cost:,.2f}",     "R", DARK_GRAY),
            (f"${tot_gain:,.2f}",     "R", tot_color),
        ]
        x_cursor = margin
        c.setFont("Helvetica-Bold", 7)
        for (val, align, col_color), (_, col_w, _) in zip(totals_vals, _COLS):
            c.setFillColor(col_color)
            if align == "R":
                c.drawRightString(x_cursor + col_w - 2, y - _ROW_H + 3, val)
            else:
                c.drawString(x_cursor + 2, y - _ROW_H + 3, val)
            x_cursor += col_w
        y -= _ROW_H
        c.setStrokeColor(DARK_GRAY)
        c.setLineWidth(0.6)
        c.line(margin, y, margin + _TOTAL_COL_W, y)


def build_1099da_pdf(tax_data: dict, tax_year: int = None) -> bytes:
    """
    Build an IRS Form 1099-DA PDF.

    Args:
        tax_data: dict with keys short_term, long_term (each containing
                  proceeds, cost_basis, gain_loss, count) and optionally
                  dispositions (list of per-disposition dicts from FIFO calc).
        tax_year: Tax year (defaults to previous calendar year).

    Returns:
        PDF bytes.
    """
    if tax_year is None:
        tax_year = date.today().year - 1

    buf = io.BytesIO()
    width, height = letter
    c = canvas.Canvas(buf, pagesize=letter)

    margin = 0.5 * inch
    content_width = width - 2 * margin
    footer_y = margin + 15

    all_dispositions = tax_data.get("dispositions", [])

    def render_form_page(section_label: str, section_data: dict, page_num: int) -> float:
        """
        Draw the 1099-DA form boxes for one section.
        Returns the y coordinate at the bottom of the summary box.
        """
        y = height - margin

        c.setFillColor(BTC_ORANGE)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margin, y - 18, "Form 1099-DA")
        c.setFont("Helvetica", 9)
        c.setFillColor(DARK_GRAY)
        c.drawString(margin, y - 32,
                     f"Digital Asset Proceeds from Broker and Barter Exchange Transactions — Tax Year {tax_year}")
        c.drawRightString(width - margin, y - 32, f"Page {page_num}")

        c.setStrokeColor(BTC_ORANGE)
        c.setLineWidth(1.5)
        c.line(margin, y - 38, width - margin, y - 38)

        top_y = y - 50
        box_h = 35
        third = content_width / 3

        _draw_box(c, margin, top_y - box_h, third, box_h,
                  "PAYER'S name, address, city, state, ZIP", "(Leave blank — fill in manually)")
        _draw_box(c, margin + third, top_y - box_h, third, box_h,
                  "PAYER'S TIN", "(Leave blank)")
        _draw_box(c, margin + 2 * third, top_y - box_h, third, box_h,
                  "RECIPIENT'S TIN", "(Leave blank)")

        row2_y = top_y - box_h - 5
        _draw_box(c, margin, row2_y - box_h, third * 2, box_h,
                  "RECIPIENT'S name, address, city, state, ZIP", "(Leave blank — fill in manually)")
        _draw_box(c, margin + 2 * third, row2_y - box_h, third, box_h,
                  "Account number", "(Leave blank)")

        data_y = row2_y - box_h - 15
        c.setFillColor(BTC_ORANGE)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, data_y, f"CALCULATED DATA — {section_label}")
        c.setStrokeColor(MID_GRAY)
        c.line(margin, data_y - 4, width - margin, data_y - 4)

        proceeds  = section_data.get("proceeds", 0.0)
        cost_basis = section_data.get("cost_basis", 0.0)
        gain_loss  = section_data.get("gain_loss", 0.0)
        count      = section_data.get("count", 0)

        is_long   = "long" in section_label.lower()
        term_code = "D" if is_long else "A"

        boxes_y = data_y - 15
        col_w   = content_width / 4

        _draw_box(c, margin,             boxes_y - box_h, col_w, box_h,
                  "Box 1a  Acquisition date (approximate)", "Various")
        _draw_box(c, margin + col_w,     boxes_y - box_h, col_w, box_h,
                  "Box 1b  Date of sale or disposition", f"{tax_year}/12/31 (approximate)")
        _draw_box(c, margin + 2 * col_w, boxes_y - box_h, col_w, box_h,
                  "Box 1c  Proceeds (USD)", f"${proceeds:,.2f}")
        _draw_box(c, margin + 3 * col_w, boxes_y - box_h, col_w, box_h,
                  "Box 1d  Cost or other basis (USD)", f"${cost_basis:,.2f}")

        boxes_y2 = boxes_y - box_h - 5
        _draw_box(c, margin,             boxes_y2 - box_h, col_w, box_h,
                  "Box 1e  Adjustment codes", "")
        _draw_box(c, margin + col_w,     boxes_y2 - box_h, col_w, box_h,
                  "Box 1f  Adjustment amount", "")

        gain_color = colors.HexColor("#C62828") if gain_loss < 0 else colors.HexColor("#1B5E20")
        _draw_box(c, margin + 2 * col_w, boxes_y2 - box_h, col_w, box_h,
                  "Box 1g  Net gain or loss (USD)", f"${gain_loss:,.2f}")
        c.setFillColor(gain_color)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin + 2 * col_w + 4, boxes_y2 - box_h + 5, f"${gain_loss:,.2f}")

        _draw_box(c, margin + 3 * col_w, boxes_y2 - box_h, col_w, box_h,
                  "Box 2  Short/long-term", "Long-term (D)" if is_long else "Short-term (A)")

        boxes_y3 = boxes_y2 - box_h - 5
        _draw_box(c, margin,             boxes_y3 - box_h, col_w, box_h,
                  "Box 3  Collectibles", "No")
        _draw_box(c, margin + col_w,     boxes_y3 - box_h, col_w * 2, box_h,
                  "Number of dispositions included", str(count))
        _draw_box(c, margin + 3 * col_w, boxes_y3 - box_h, col_w, box_h,
                  "IRS Form code", term_code)

        summary_y = boxes_y3 - box_h - 20
        c.setFillColor(LIGHT_GRAY)
        c.setStrokeColor(MID_GRAY)
        c.rect(margin, summary_y - 55, content_width, 55, fill=1, stroke=1)

        c.setFillColor(BTC_ORANGE)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(margin + 5, summary_y - 12, "SUMMARY")

        c.setFillColor(DARK_GRAY)
        summary_rows = [
            ("Total Proceeds:",   f"${proceeds:,.2f}"),
            ("Total Cost Basis:", f"${cost_basis:,.2f}"),
            ("Net Gain / (Loss):", f"${gain_loss:,.2f}"),
        ]
        for i, (lbl, val) in enumerate(summary_rows):
            ry = summary_y - 22 - i * 12
            c.setFont("Helvetica", 8)
            c.setFillColor(DARK_GRAY)
            c.drawString(margin + 5, ry, lbl)
            c.setFont("Helvetica-Bold", 8)
            if "Gain" in lbl:
                c.setFillColor(gain_color)
            c.drawString(margin + 180, ry, val)
            c.setFillColor(DARK_GRAY)

        _draw_footer(c, width, footer_y)
        return summary_y - 55  # bottom edge of summary box

    def render_continuation_header(section_label: str, page_num: int) -> float:
        """Render a minimal header for overflow disposition pages. Returns start_y for the table."""
        y = height - margin
        c.setFillColor(BTC_ORANGE)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, y - 18, "Form 1099-DA  —  Disposition Detail (continued)")
        c.setFont("Helvetica", 9)
        c.setFillColor(DARK_GRAY)
        c.drawString(margin, y - 32, f"Tax Year {tax_year}  |  {section_label}")
        c.drawRightString(width - margin, y - 32, f"Page {page_num}")
        c.setStrokeColor(BTC_ORANGE)
        c.setLineWidth(1.5)
        c.line(margin, y - 38, width - margin, y - 38)
        _draw_footer(c, width, footer_y)
        return y - 50

    # ── Render all sections ─────────────────────────────────────────────────────

    sections = [
        ("Short-Term Capital Gains/Losses (Held ≤365 days)", tax_data.get("short_term", {}), "short"),
        ("Long-Term Capital Gains/Losses (Held >365 days)",  tax_data.get("long_term", {}),  "long"),
    ]

    page_num = 0
    for sec_idx, (label, section_data, term_key) in enumerate(sections):
        if sec_idx > 0:
            c.showPage()
        page_num += 1

        summary_bottom = render_form_page(label, section_data, page_num)

        # Filter dispositions for this section (short or long)
        section_dispositions = [d for d in all_dispositions if d.get("term") == term_key]

        if not section_dispositions:
            continue

        # Render disposition table, paginating if needed
        remaining   = list(section_dispositions)
        row_offset  = 0
        first_chunk = True

        while remaining:
            if first_chunk:
                start_y = summary_bottom - 12
            else:
                c.showPage()
                page_num += 1
                start_y = render_continuation_header(label, page_num)

            max_rows   = _max_rows_fitting(start_y, footer_y)
            page_rows  = remaining[:max_rows]
            remaining  = remaining[max_rows:]
            is_last    = len(remaining) == 0

            if page_rows:
                _draw_disposition_chunk(
                    c,
                    page_rows       = page_rows,
                    all_section_rows= section_dispositions,
                    start_y         = start_y,
                    margin          = margin,
                    section_label   = label,
                    row_offset      = row_offset,
                    is_continuation = not first_chunk,
                    is_last_page    = is_last,
                )
                row_offset += len(page_rows)

            first_chunk = False

    c.save()
    buf.seek(0)
    return buf.read()
