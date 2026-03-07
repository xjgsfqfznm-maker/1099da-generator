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


def build_1099da_pdf(tax_data: dict, tax_year: int = None) -> bytes:
    """
    Build a draft IRS Form 1099-DA PDF.

    Args:
        tax_data: dict with keys short_term and long_term, each containing
                  proceeds, cost_basis, gain_loss, count
        tax_year: Tax year (defaults to previous calendar year)

    Returns:
        PDF bytes
    """
    if tax_year is None:
        tax_year = date.today().year - 1

    buf = io.BytesIO()
    width, height = letter
    c = canvas.Canvas(buf, pagesize=letter)

    def render_page(section_label: str, section_data: dict, page_num: int, total_pages: int) -> None:
        margin = 0.5 * inch
        content_width = width - 2 * margin

        y = height - margin

        c.setFillColor(BTC_ORANGE)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margin, y - 18, f"Form 1099-DA")
        c.setFont("Helvetica", 9)
        c.setFillColor(DARK_GRAY)
        c.drawString(margin, y - 32, f"Digital Asset Proceeds from Broker and Barter Exchange Transactions — Tax Year {tax_year}")
        c.drawRightString(width - margin, y - 32, f"Page {page_num} of {total_pages}")

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

        proceeds = section_data.get("proceeds", 0.0)
        cost_basis = section_data.get("cost_basis", 0.0)
        gain_loss = section_data.get("gain_loss", 0.0)
        count = section_data.get("count", 0)

        is_long = "long" in section_label.lower()
        term_code = "D" if is_long else "A"

        boxes_y = data_y - 15
        col_w = content_width / 4

        _draw_box(c, margin, boxes_y - box_h, col_w, box_h,
                  "Box 1a  Acquisition date (approximate)", "Various")
        _draw_box(c, margin + col_w, boxes_y - box_h, col_w, box_h,
                  "Box 1b  Date of sale or disposition", f"{tax_year}/12/31 (approximate)")
        _draw_box(c, margin + 2 * col_w, boxes_y - box_h, col_w, box_h,
                  "Box 1c  Proceeds (USD)", f"${proceeds:,.2f}")
        _draw_box(c, margin + 3 * col_w, boxes_y - box_h, col_w, box_h,
                  "Box 1d  Cost or other basis (USD)", f"${cost_basis:,.2f}")

        boxes_y2 = boxes_y - box_h - 5
        _draw_box(c, margin, boxes_y2 - box_h, col_w, box_h,
                  "Box 1e  Adjustment codes", "")
        _draw_box(c, margin + col_w, boxes_y2 - box_h, col_w, box_h,
                  "Box 1f  Adjustment amount", "")

        gain_color = colors.HexColor("#C62828") if gain_loss < 0 else colors.HexColor("#1B5E20")
        _draw_box(c, margin + 2 * col_w, boxes_y2 - box_h, col_w, box_h,
                  "Box 1g  Net gain or loss (USD)",
                  f"${gain_loss:,.2f}")

        c.setFillColor(gain_color)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin + 2 * col_w + 4, boxes_y2 - box_h + 5, f"${gain_loss:,.2f}")

        _draw_box(c, margin + 3 * col_w, boxes_y2 - box_h, col_w, box_h,
                  "Box 2  Short/long-term", "Long-term (D)" if is_long else "Short-term (A)")

        boxes_y3 = boxes_y2 - box_h - 5
        _draw_box(c, margin, boxes_y3 - box_h, col_w, box_h,
                  "Box 3  Collectibles", "No")
        _draw_box(c, margin + col_w, boxes_y3 - box_h, col_w * 2, box_h,
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
        c.setFont("Helvetica", 8)
        rows = [
            ("Total Proceeds:", f"${proceeds:,.2f}"),
            ("Total Cost Basis:", f"${cost_basis:,.2f}"),
            ("Net Gain / (Loss):", f"${gain_loss:,.2f}"),
        ]
        col1_x = margin + 5
        col2_x = margin + 180
        for i, (lbl, val) in enumerate(rows):
            row_y = summary_y - 22 - i * 12
            c.setFont("Helvetica", 8)
            c.setFillColor(DARK_GRAY)
            c.drawString(col1_x, row_y, lbl)
            c.setFont("Helvetica-Bold", 8)
            if "Gain" in lbl and gain_loss < 0:
                c.setFillColor(colors.HexColor("#C62828"))
            elif "Gain" in lbl:
                c.setFillColor(colors.HexColor("#1B5E20"))
            c.drawString(col2_x, row_y, val)
            c.setFillColor(DARK_GRAY)

        footer_y = margin + 15
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.HexColor("#888888"))
        c.drawCentredString(width / 2, footer_y,
                            "Generated from self-custodial wallet data. "
                            "NOT tax advice. Verify with a qualified CPA or tax professional. "
                            "This form is not submitted to the IRS.")

    sections = [
        ("Short-Term Capital Gains/Losses (Held ≤365 days)", tax_data.get("short_term", {})),
        ("Long-Term Capital Gains/Losses (Held >365 days)", tax_data.get("long_term", {})),
    ]
    total_pages = len(sections)

    for i, (label, section) in enumerate(sections):
        render_page(label, section, i + 1, total_pages)
        if i < total_pages - 1:
            c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
