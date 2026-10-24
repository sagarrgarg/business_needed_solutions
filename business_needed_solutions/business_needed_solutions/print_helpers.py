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

FILL_MARKERS = (
	"BNSMKS",
	"BNSMKT",
	"BNSMKH",
	"BNSMKA",
	"BNSMKB",
	"BNSMKC",
	"BNSMKZ",
	"BNSMKW",
	"BNSMKD",
	"BNSMKE",
)
# Measuring pass prints a column of BNSMKZ lines, each RULER_STEP_PT tall, after the
# closing block. The last one on that page shows exactly where the page body ends.
RULER_STEP_PT = 3.0
# wkhtmltopdf draws a ruler line that straddles the page cut on both pages, so the last
# ruler line can sit ~7pt past the real cut. Keeping the block 12pt above the last ruler
# line (~4mm) held across 1-60 line invoices; 8pt split the block on some pages.
_SLACK_PT = 12.0
_MIN_ROW_PT = 4.0
_BLOCK_GAP_PT = 5.7  # .final-tax-total-table margin-top: 2mm


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
	plan = _closing_block_plan(marks)
	if plan is not None:
		plan.update(_ewaybill_plan(marks))
	return plan


def _page_body(marks: dict) -> tuple[float, float] | None:
	"""(body_top, body_bottom) in pt, the same on every page (same header/footer)."""
	try:
		body_top = marks["BNSMKS"][0][1]
		page_c = marks["BNSMKC"][0][0]
	except (KeyError, IndexError):
		return None
	ruler = [top for page, top in marks.get("BNSMKZ", []) if page == page_c]
	return (body_top, max(ruler)) if ruler else None


def _ewaybill_plan(marks: dict) -> dict:
	"""Make the e-Waybill page fill exactly one page.

	Short of a page: stretch its details table so the rows spread to the page foot.
	Longer than a page: scale the whole page down (CSS zoom) so it fits on one.
	"""
	body = _page_body(marks)
	try:
		page_w, top = marks["BNSMKW"][-1]
		page_d, details_top = marks["BNSMKD"][-1]
		page_e, end = marks["BNSMKE"][0]
	except (KeyError, IndexError):
		return {}
	if not body:
		return {}
	body_top, body_bottom = body
	limit = body_bottom - _SLACK_PT
	if page_e == page_w and page_d == page_w and end <= limit:
		return {"ewb_details_pt": round(end - details_top + (limit - end), 1)}
	natural = end - top if page_e == page_w else (body_bottom - top) + (end - body_top)
	return {"ewb_zoom": round(max(0.5, (limit - body_top) / natural) * 0.98, 3)}


def _closing_block_plan(marks: dict) -> dict | None:
	# A marker that falls exactly on a page cut is drawn on both pages. What follows a
	# start marker continues on the later page, so it belongs there; end markers close
	# what came before, so they belong to the earlier page.
	try:
		page_a, items_end = marks["BNSMKA"][0]
		page_b, block_top = marks["BNSMKB"][-1]
		page_c, block_end = marks["BNSMKC"][0]
		body_top = marks["BNSMKS"][0][1]
	except (KeyError, IndexError):
		return None

	no_fill = {"measure": False, "rows": [], "keep_block": False}

	# Every page has the same header and footer, so one body top/bottom fits all pages.
	ruler = [top for page, top in marks.get("BNSMKZ", []) if page == page_c]
	if not ruler:
		return no_fill
	body_bottom = max(ruler)

	head = 0.0
	if marks.get("BNSMKT") and marks.get("BNSMKH"):
		head = max(0.0, marks["BNSMKH"][0][1] - marks["BNSMKT"][0][1])

	# wkhtmltopdf does not reliably keep the block whole, so it may have split across a
	# page cut while measuring; rebuild its height from both halves.
	if page_c == page_b:
		block_height = block_end - block_top
	elif page_c == page_b + 1:
		block_height = (body_bottom - block_top) + (block_end - body_top)
	else:
		return no_fill
	# Space between the item table and the block (the block's top margin).
	gap = block_top - items_end if page_b == page_a else _BLOCK_GAP_PT

	if block_height + head + gap + _SLACK_PT > body_bottom - body_top:
		return no_fill  # the block alone is taller than a page: let it flow

	rows = []
	room_under_items = body_bottom - _SLACK_PT - (items_end + gap + block_height)
	if page_b == page_a and page_c == page_a and room_under_items >= 0:
		# Fits under the items with the safety gap: one fill row pushes it to the foot.
		rows.append(room_under_items)
	else:
		# Does not fit: fill the items page to its foot, then on the next page (item
		# header repeats) fill down to where the block must start to end at the foot.
		rows.append(body_bottom - items_end - _SLACK_PT)
		rows.append(body_bottom - body_top - head - gap - block_height - _SLACK_PT)

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
