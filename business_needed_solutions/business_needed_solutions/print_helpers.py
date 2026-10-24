"""Jinja helpers for BNS print formats."""

import importlib.util
from io import BytesIO

import frappe
import pyqrcode


def get_einvoice_qr_code(qr_text: str, size_px_per_module: int = 6) -> str:
	"""Return the IRP signed QR as a base64 PNG, built to stay readable when printed small.

	India Compliance's ``get_qr_code`` uses error correction H. A ~950 character signed QR
	then needs a version 34 symbol (153 modules), whose modules are only ~0.22 mm wide at a
	34 mm print size. Level M (15% recovery, the usual default for printed codes) needs
	version 25 (117 modules), so each module is ~30% larger at the same size and still
	scans after print blur. A higher pixel scale keeps module edges sharp in the PDF.
	"""
	if not qr_text:
		return ""
	return pyqrcode.create(qr_text, error="M").png_as_base64_str(scale=size_px_per_module, quiet_zone=1)


# --- Tally-style fill -----------------------------------------------------------------
#
# wkhtmltopdf runs with JavaScript off, so a template cannot see where a page ends. The
# template therefore asks for a fill plan: we render the same document once to PDF with
# invisible markers (items end, closing block start/end, footer top, item header) and read
# where they landed. The real render then adds empty item rows of exactly that height, so
# the closing block (bank details, totals, HSN, payment, T&C) sits at the foot of the page
# and the item columns run down to it, as in Tally. If the closing block does not fit
# under the items, the items page is filled to its foot and the block sits at the foot of
# the next page.

FILL_MARKERS = ("BNSMKT", "BNSMKH", "BNSMKA", "BNSMKB", "BNSMKC", "BNSMKZ")
# Measuring pass prints a column of BNSMKZ lines, each RULER_STEP_PT tall, after the
# closing block. The last one on that page shows exactly where the page body ends.
RULER_STEP_PT = 3.0
# wkhtmltopdf draws a ruler line that straddles the page cut on both pages, so the ruler
# reads ~9pt low; this slack absorbs that and keeps the block whole (tested 8pt splits).
_SLACK_PT = 10.0
_MIN_ROW_PT = 4.0


def get_tally_fill_plan(doc, print_format: str) -> dict:
	"""Plan of empty item-row heights (pt) that pin the closing block to the page foot.

	Returns ``{"measure": True}`` while measuring (the template then prints markers),
	otherwise ``{"measure": False, "rows": [pt, ...], "keep_block": bool}``. Any failure
	falls back to no fill, so printing never breaks because of this.
	"""
	if frappe.flags.bns_fill_measuring:
		return {"measure": True, "rows": [], "keep_block": True}

	plan = {"measure": False, "rows": [], "keep_block": False}
	if not importlib.util.find_spec("pdfplumber"):  # shipped with ERPNext
		return plan

	frappe.flags.bns_fill_measuring = True
	try:
		pdf = frappe.get_print(
			doc.doctype,
			doc.name,
			print_format,
			doc=doc,
			as_pdf=True,
			no_letterhead=frappe.form_dict.get("no_letterhead") or 0,
			letterhead=frappe.form_dict.get("letterhead"),
		)
		return _plan_from_pdf(pdf) or plan
	except Exception:
		frappe.log_error(title="BNS print: Tally fill measure failed")
		return plan
	finally:
		frappe.flags.bns_fill_measuring = False


def _plan_from_pdf(pdf: bytes) -> dict | None:
	marks = _marker_positions(pdf)
	try:
		page_a, items_end = marks["BNSMKA"][0]
		page_b, _block_top = marks["BNSMKB"][0]
		page_c, block_end = marks["BNSMKC"][0]
	except (KeyError, IndexError):
		return None

	if page_b != page_c:
		# Closing block is taller than a page: let it flow, no fill.
		return {"measure": False, "rows": [], "keep_block": False}

	# Every page has the same header and footer, so one body bottom fits all pages.
	ruler = [top for page, top in marks.get("BNSMKZ", []) if page == page_c]
	if not ruler:
		return {"measure": False, "rows": [], "keep_block": True}
	body_bottom = max(ruler) + RULER_STEP_PT

	head = 0.0
	if marks.get("BNSMKT") and marks.get("BNSMKH"):
		head = max(0.0, marks["BNSMKH"][0][1] - marks["BNSMKT"][0][1])

	rows = []
	if page_b == page_a:
		rows.append(body_bottom - block_end - _SLACK_PT)
	elif page_b == page_a + 1:
		rows.append(body_bottom - items_end - _SLACK_PT)
		rows.append(body_bottom - block_end - head - _SLACK_PT)
	else:
		return {"measure": False, "rows": [], "keep_block": True}

	return {
		"measure": False,
		"rows": [round(r, 1) for r in rows if r >= _MIN_ROW_PT],
		"keep_block": True,
	}


def _marker_positions(pdf: bytes) -> dict[str, list[tuple[int, float]]]:
	"""{marker: [(page_index, top_pt), ...]} in page order."""
	import pdfplumber

	found: dict[str, list[tuple[int, float]]] = {}
	with pdfplumber.open(BytesIO(pdf)) as document:
		for index, page in enumerate(document.pages):
			for char_run in page.extract_words(keep_blank_chars=False, use_text_flow=True):
				text = char_run["text"]
				for marker in FILL_MARKERS:
					if marker in text:
						found.setdefault(marker, []).append((index, float(char_run["top"])))
	return found
